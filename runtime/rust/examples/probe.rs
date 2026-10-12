//! Development probe, not a serving CLI. Uses a trusted golden prompt as input.
use anyhow::{bail, ensure, Context, Result};
use candle_core::{safetensors::MmapedSafetensors, DType, Device, Tensor};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path},
    time::Instant,
};

fn digest(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut hash = Sha256::new();
    let mut bytes = [0_u8; 65536];
    loop {
        let n = file.read(&mut bytes)?;
        if n == 0 {
            break;
        }
        hash.update(&bytes[..n]);
    }
    Ok(format!("{:x}", hash.finalize()))
}

fn array(value: &Value) -> Result<Vec<f32>> {
    value
        .as_array()
        .context("expected float array")?
        .iter()
        .map(|v| {
            v.as_f64()
                .filter(|v| v.is_finite())
                .map(|v| v as f32)
                .context("invalid float")
        })
        .collect()
}

fn max_error(actual: &[f32], expected: &[f32]) -> Result<f32> {
    ensure!(actual.len() == expected.len(), "dimension mismatch");
    ensure!(!actual.is_empty(), "empty comparison");
    ensure!(
        actual.iter().chain(expected).all(|v| v.is_finite()),
        "nonfinite output"
    );
    Ok(actual
        .iter()
        .zip(expected)
        .map(|(a, b)| (a - b).abs())
        .fold(0_f32, f32::max))
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 4 || args.len() == 5,
        "usage: probe manifest golden output [--full]"
    );
    let full = args.len() == 5;
    ensure!(!full || args[4] == "--full", "unknown mode");
    let output = Path::new(&args[3]);
    ensure!(!output.exists(), "output already exists");
    let started = Instant::now();
    let manifest_path = Path::new(&args[1]);
    let golden_path = Path::new(&args[2]);
    let manifest: Value = serde_json::from_slice(&fs::read(manifest_path)?)?;
    let golden: Value = serde_json::from_slice(&fs::read(golden_path)?)?;
    ensure!(
        golden["schema_version"] == "kaze_judge.jeff_golden.v1",
        "unsupported reference"
    );
    ensure!(
        manifest["schema_version"] == "pure_jeff.reference_bundle.v1",
        "unsupported bundle"
    );
    ensure!(
        golden["provenance"]["manifest_sha256"] == digest(manifest_path)?,
        "manifest/reference mismatch"
    );
    let checkpoint =
        Path::new(manifest["checkpoint"].as_str().context("checkpoint path")?).canonicalize()?;
    for record in manifest["checkpoint_files"]
        .as_array()
        .context("checkpoint inventory")?
    {
        let relative = Path::new(record["path"].as_str().context("asset path")?);
        ensure!(
            relative
                .components()
                .all(|c| matches!(c, Component::Normal(_))),
            "invalid asset path"
        );
        let path = checkpoint.join(relative);
        ensure!(
            !fs::symlink_metadata(&path)?.file_type().is_symlink(),
            "symlink asset"
        );
        ensure!(
            path.canonicalize()?.starts_with(&checkpoint),
            "asset escapes checkpoint"
        );
        ensure!(
            record["sha256"] == digest(&path)?,
            "asset differs: {}",
            path.display()
        );
    }
    let config: Value = serde_json::from_slice(&fs::read(checkpoint.join("config.json"))?)?;
    let text = &config["text_config"];
    ensure!(config["model_type"] == "qwen3_5", "unsupported model");
    for (key, expected) in [
        ("hidden_size", 1024),
        ("num_hidden_layers", 24),
        ("num_attention_heads", 8),
        ("num_key_value_heads", 2),
        ("head_dim", 256),
        ("intermediate_size", 3584),
        ("linear_num_value_heads", 16),
        ("linear_num_key_heads", 16),
        ("linear_key_head_dim", 128),
        ("linear_value_head_dim", 128),
        ("linear_conv_kernel_dim", 4),
    ] {
        ensure!(text[key] == expected, "unsupported config {key}");
    }
    ensure!(
        text["attention_bias"] == false && text["hidden_act"] == "silu",
        "unsupported attention/activation"
    );
    ensure!(text["rms_norm_eps"] == 1e-6, "unsupported norm epsilon");
    ensure!(
        text["rope_parameters"]["rope_theta"] == 10_000_000
            && text["rope_parameters"]["rope_type"] == "default"
            && text["rope_parameters"]["partial_rotary_factor"] == 0.25,
        "unsupported rope"
    );
    let types = text["layer_types"].as_array().context("layer types")?;
    ensure!(
        types.len() == 24
            && types.iter().enumerate().all(|(i, v)| v
                == if i % 4 == 3 {
                    "full_attention"
                } else {
                    "linear_attention"
                }),
        "unsupported layer layout"
    );
    let tokenizer = tokenizers::Tokenizer::from_file(checkpoint.join("tokenizer.json"))
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let prompt = golden["prompt"].as_str().context("prompt")?;
    ensure!(
        golden["prompt_utf8_sha256"] == format!("{:x}", Sha256::digest(prompt.as_bytes())),
        "prompt digest mismatch"
    );
    let encoding = tokenizer
        .encode(prompt, false)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    let ids = encoding.get_ids();
    let expected_ids: Vec<u32> =
        serde_json::from_value(golden["official"]["inputs"]["input_ids"][0].clone())?;
    ensure!(ids == expected_ids, "token IDs differ");
    let attention_mask: Vec<u32> =
        serde_json::from_value(golden["official"]["inputs"]["attention_mask"][0].clone())?;
    ensure!(
        attention_mask.len() == ids.len() && attention_mask.iter().all(|v| *v == 1),
        "padding unsupported"
    );
    ensure!(
        !ids.is_empty() && ids.len() <= 8192,
        "unsupported input length"
    );
    let expected_hidden = array(&golden["official"]["last_hidden_state"][0])?;
    ensure!(expected_hidden.len() == 1024, "unsupported hidden width");
    // SAFETY: trusted local assets were hashed above and must remain immutable
    // throughout this probe. This does not prevent concurrent file mutation.
    let hidden = if full {
        let weights = unsafe { MmapedSafetensors::new(checkpoint.join("model.safetensors"))? };
        pure_jeff::backbone::forward(&weights, ids)?
    } else {
        Tensor::from_vec(expected_hidden.clone(), (1, 1024), &Device::Cpu)?
    };
    let hidden_values = hidden.flatten_all()?.to_vec1::<f32>()?;
    let hidden_error = max_error(&hidden_values, &expected_hidden)?;
    // SAFETY: same immutable, verified local-asset precondition as above.
    let readout = unsafe { MmapedSafetensors::new(checkpoint.join("readout.safetensors"))? };
    let weight = readout.load("weight", &Device::Cpu)?.to_dtype(DType::F32)?;
    ensure!(weight.dims() == [255, 1024], "readout shape");
    let logits = hidden.matmul(&weight.t()?)?.flatten_all()?;
    let logits_values = logits.to_vec1::<f32>()?;
    let logits_error = max_error(
        &logits_values,
        &array(&golden["official"]["unmasked_logits"][0])?,
    )?;
    let count = golden["request"]["candidates"]
        .as_array()
        .context("candidates")?
        .len();
    ensure!((2..=255).contains(&count), "invalid candidate count");
    let temp = golden["temperature"].as_f64().context("temperature")?;
    ensure!(temp.is_finite() && temp > 0.0, "invalid temperature");
    let masked: Vec<f32> = logits_values
        .iter()
        .enumerate()
        .map(|(i, v)| if i < count { *v } else { -1e9 })
        .collect();
    let probs = candle_nn::ops::softmax_last_dim(
        &(Tensor::from_vec(masked, (1, 255), &Device::Cpu)? / temp)?,
    )?
    .flatten_all()?
    .narrow(0, 0, count)?
    .to_vec1::<f32>()?;
    let error = max_error(&probs, &array(&golden["official"]["probabilities"])?)?;
    let probability_floor = manifest["policy"]["min_probability"]
        .as_f64()
        .context("probability floor")?;
    let margin_floor = manifest["policy"]["min_margin"]
        .as_f64()
        .context("margin floor")?;
    ensure!(
        [probability_floor, margin_floor]
            .iter()
            .all(|v| v.is_finite() && (0.0..=1.0).contains(v)),
        "invalid policy"
    );
    let mut order: Vec<usize> = (0..count).collect();
    order.sort_by(|a, b| probs[*b].total_cmp(&probs[*a]));
    let best = probs[order[0]] as f64;
    let margin = best - probs[order[1]] as f64;
    let judgment = if margin > 0.0 && margin >= margin_floor && best >= probability_floor {
        json!({"kind":"selected", "candidate_id":golden["request"]["candidates"][order[0]]["id"]})
    } else {
        json!({"kind":"abstained"})
    };
    let judgment_match = judgment == golden["official"]["judgment"];
    let result = json!({"schema_version":"kaze_judge.rust_probe.v1", "mode":if full {"full_backbone"} else {"tokenizer_readout"},
        "reference_sha256":digest(golden_path)?, "manifest_sha256":digest(manifest_path)?,
        "input_tokens":ids.len(), "token_ids_match":true, "hidden_max_absolute_error":hidden_error,
        "logits_max_absolute_error":logits_error, "probabilities_max_absolute_error":error,
        "probabilities":probs, "hidden":hidden_values, "logits":logits_values,
        "judgment":judgment, "judgment_matches":judgment_match,
        "gemm_threads":candle_core::utils::get_num_threads(),
        "candle_revision":"c68b24997319b8d76e5a4e775dab197c7f26322a",
        "backbone_sha256":format!("{:x}",Sha256::digest(include_bytes!("../../../src/backbone.rs"))),
        "probe_sha256":format!("{:x}",Sha256::digest(include_bytes!("probe.rs"))),
        "elapsed_ms":started.elapsed().as_millis(), "probability_target":1e-4, "target_passed":error<=1e-4 && judgment_match});
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?;
    serde_json::to_writer_pretty(&mut file, &result)?;
    file.write_all(b"\n")?;
    println!(
        "{}",
        json!({"mode":result["mode"], "tokens":ids.len(), "hidden_error":hidden_error,
        "logits_error":logits_error, "probability_error":error,"elapsed_ms":result["elapsed_ms"]})
    );
    if error > 1e-4 || !judgment_match {
        bail!("probability or judgment target failed; diagnostic output saved");
    }
    Ok(())
}
