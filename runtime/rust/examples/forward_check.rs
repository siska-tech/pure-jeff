//! Diagnostic: runs the library forward on official golden fixtures and prints, per case, the
//! SHA-256 of the final hidden state's f32 bytes, the forward time and the probability difference
//! from the official reference. Two builds produce bitwise-equal forwards when every hash matches.
//! Does not require the manifest to be locked by this build.
//!
//!   cargo run --release --example forward_check -- <manifest> <golden.json>... [--reps N]
use anyhow::{ensure, Context, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
};
use pure_jeff::{DecisionRequest, Limits};
use std::{
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Official {
    inputs: serde_json::Value,
    probabilities: Vec<f64>,
    judgment: serde_json::Value,
}

#[derive(serde::Deserialize)]
struct Golden {
    request: DecisionRequest,
    official: Official,
}

fn main() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let reps = match args.iter().position(|a| a == "--reps") {
        Some(i) => {
            let value = args.remove(i + 1).parse()?;
            args.remove(i);
            value
        }
        None => 1,
    };
    let (manifest, cases) = args
        .split_first()
        .context("usage: forward_check <manifest> <golden.json>... [--reps N]")?;
    ensure!(
        reps >= 1 && !cases.is_empty(),
        "need at least one case and one rep"
    );
    let deadline = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    header.policy.validate()?;
    std::env::set_var("RAYON_NUM_THREADS", header.policy.cpu_threads.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", header.policy.cpu_threads.to_string());
    let bundle = Bundle::verify(Path::new(manifest), deadline, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    // SAFETY: as above.
    let readout_weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("readout.safetensors"))?
    };
    ensure!(
        candle_core::utils::get_num_threads() == bundle.manifest.policy.cpu_threads,
        "compute threads differ from the bundle policy"
    );
    for path in cases {
        let golden: Golden = bundle::read_json(Path::new(path), 64 * 1024 * 1024)?;
        let prepared = tokenizer.prepare(
            &bundle.decision,
            &golden.request,
            Limits {
                max_input_bytes: 1024 * 1024,
                max_input_tokens: 8192,
                max_forwards: 1,
                deadline,
            },
        )?;
        let official_ids: Vec<u32> =
            serde_json::from_value(golden.official.inputs["input_ids"][0].clone())?;
        ensure!(
            prepared.ids == official_ids,
            "{path}: token IDs differ from the official ones"
        );
        let mut hashes = Vec::new();
        let mut forward_s = Vec::new();
        let mut probabilities = Vec::new();
        for _ in 0..reps {
            let step = Instant::now();
            let hidden = backbone::forward(&weights, &prepared.ids)?;
            forward_s.push(step.elapsed().as_secs_f64());
            let bytes: Vec<u8> = hidden
                .flatten_all()?
                .to_vec1::<f32>()?
                .iter()
                .flat_map(|v| v.to_le_bytes())
                .collect();
            hashes.push(bundle::hash_bytes(&bytes));
            probabilities = readout::probabilities(
                &readout_weights,
                &hidden,
                golden.request.candidates.len(),
                bundle.decision.temperature,
            )?;
        }
        ensure!(
            hashes.iter().all(|h| *h == hashes[0]),
            "{path}: repeats differ"
        );
        let max_diff = probabilities
            .iter()
            .zip(&golden.official.probabilities)
            .map(|(a, b)| (a - b).abs())
            .fold(0.0, f64::max);
        let judgment = bundle
            .manifest
            .policy
            .judge(&golden.request, &probabilities)?;
        println!(
            "{}",
            serde_json::json!({"case": Path::new(path).file_stem().unwrap().to_string_lossy(),
                "input_tokens": prepared.ids.len(), "hidden_sha256": hashes[0],
                "forward_s": forward_s, "max_probability_diff": max_diff,
                "judgment_matches": serde_json::to_value(&judgment)? == golden.official.judgment})
        );
    }
    Ok(())
}
