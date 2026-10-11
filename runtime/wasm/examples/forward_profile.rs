//! Where the Native forward spends its time (diagnostic, one thread, memory-mapped BF16 weights).
//! Runs the frozen forward once per case to compare, then the profiled copy `--reps` times, and
//! requires the profiled hidden state to be bitwise equal to the frozen one.
//!
//!   cargo run --release --example forward_profile -- <bundle manifest> <golden.json>... [--reps N]
use anyhow::{ensure, Context, Result};
use candle_core::safetensors::MmapedSafetensors;
use kaze_judge::DecisionRequest;
use kaze_judge_wasm_probe::{frozen, profile, profiled, prompt, tokenize};
use std::{path::Path, time::Instant};

fn main() -> Result<()> {
    // The frozen Native policy is one compute thread; set it before Candle starts its pool.
    std::env::set_var("RAYON_NUM_THREADS", "1");
    std::env::set_var("CANDLE_NUM_THREADS", "1");
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let reps = match args.iter().position(|a| a == "--reps") {
        Some(i) => {
            let value = args.remove(i + 1).parse()?;
            args.remove(i);
            value
        }
        None => 3,
    };
    let (manifest, cases) = args
        .split_first()
        .context("usage: forward_profile <manifest> <golden.json>...")?;
    let manifest_json: serde_json::Value = serde_json::from_slice(&std::fs::read(manifest)?)?;
    let root = Path::new(manifest).parent().unwrap().join(
        manifest_json["checkpoint_dir"]
            .as_str()
            .context("checkpoint_dir")?,
    );
    let config: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join("decision_config.json"))?)?;
    let layout = config["prompt_layout"].as_str().unwrap_or("state-first");
    let tokenizer = tokenize::load(&std::fs::read(root.join("tokenizer.json"))?)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe { MmapedSafetensors::new(root.join("model.safetensors"))? };
    ensure!(
        candle_core::utils::get_num_threads() == 1,
        "expected one compute thread"
    );
    for case in cases {
        let golden: serde_json::Value = serde_json::from_slice(&std::fs::read(case)?)?;
        let request: DecisionRequest = serde_json::from_value(golden["request"].clone())?;
        let ids = tokenizer.encode(&prompt::render(&request, &tokenizer.codes, layout)?)?;
        let expected: Vec<u32> =
            serde_json::from_value(golden["official"]["inputs"]["input_ids"][0].clone())?;
        ensure!(
            ids == expected,
            "{case}: token IDs differ from the official reference"
        );
        let reference = frozen::forward(&weights, &ids)?
            .flatten_all()?
            .to_vec1::<f32>()?;
        for rep in 0..reps {
            profile::take();
            let started = Instant::now();
            let hidden = profiled::forward(&weights, &ids)?
                .flatten_all()?
                .to_vec1::<f32>()?;
            let total = started.elapsed().as_secs_f64();
            let totals = profile::take();
            ensure!(
                hidden == reference,
                "{case}: profiled forward differs from the frozen forward"
            );
            let categories: serde_json::Map<String, serde_json::Value> = profile::NAMES
                .iter()
                .zip(totals)
                .map(|(name, seconds)| (name.to_string(), seconds.into()))
                .collect();
            println!(
                "{}",
                serde_json::json!({"case": case, "tokens": ids.len(), "rep": rep, "forward_s": total,
                    "bitwise_equal_frozen": true, "seconds": categories})
            );
        }
    }
    Ok(())
}
