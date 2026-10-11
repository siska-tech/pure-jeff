//! Benchmark-only resident Native session: verifies the bundle and loads the tokenizer once,
//! then decides every request of a job with the unchanged worker modules (mmap weights,
//! BF16-to-FP32 conversion inside each forward). Emits one JSON line per event.
use anyhow::{ensure, Result};
use kaze_judge::{DecisionRequest, Limits};
use kaze_judge_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
};
use std::{
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Case {
    name: String,
    request: DecisionRequest,
}

fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: resident_bench manifest job.json");
    let deadline = started + Duration::from_secs(3600);
    let header: Manifest = bundle::read_json(Path::new(&args[1]), 2 * 1024 * 1024)?;
    header.policy.validate()?;
    std::env::set_var("RAYON_NUM_THREADS", header.policy.cpu_threads.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", header.policy.cpu_threads.to_string());
    let cases: Vec<Case> = bundle::read_json(Path::new(&args[2]), 16 * 1024 * 1024)?;
    let step = Instant::now();
    let bundle = Bundle::verify(Path::new(&args[1]), deadline)?;
    let verify_s = step.elapsed().as_secs_f64();
    let step = Instant::now();
    let tokenizer = Tokenizer::load(&bundle)?;
    let tokenizer_s = step.elapsed().as_secs_f64();
    // SAFETY: fixed verified local assets must remain immutable throughout the benchmark.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    ensure!(
        candle_core::utils::get_num_threads() == bundle.manifest.policy.cpu_threads,
        "compute threads differ from the bundle policy"
    );
    println!(
        "{}",
        serde_json::json!({"event": "init", "verify_s": verify_s, "tokenizer_s": tokenizer_s,
            "startup_s": started.elapsed().as_secs_f64(),
            "compute_threads": candle_core::utils::get_num_threads(),
            "source_sha256": bundle::hash_bytes(include_bytes!("resident_bench.rs"))})
    );
    for case in cases {
        let begin = Instant::now();
        let prepared = tokenizer.prepare(
            &bundle,
            &case.request,
            Limits {
                max_input_bytes: 1024 * 1024,
                max_input_tokens: 8192,
                max_forwards: 1,
                deadline,
            },
        )?;
        let tokenized = begin.elapsed().as_secs_f64();
        let step = Instant::now();
        let hidden = backbone::forward(&weights, &prepared.ids)?;
        let forward_s = step.elapsed().as_secs_f64();
        let step = Instant::now();
        let probabilities = readout::probabilities(
            &bundle.root,
            &hidden,
            case.request.candidates.len(),
            bundle.decision.temperature,
        )?;
        let judgment = bundle
            .manifest
            .policy
            .judge(&case.request, &probabilities)?;
        let readout_s = step.elapsed().as_secs_f64();
        println!(
            "{}",
            serde_json::json!({"event": "decision", "name": case.name,
                "prompt_tokenize_s": tokenized, "forward_s": forward_s, "readout_policy_s": readout_s,
                "total_s": begin.elapsed().as_secs_f64(), "input_tokens": prepared.ids.len(),
                "rendered_prompt_sha256": bundle::hash_bytes(prepared.prompt.as_bytes()),
                "probabilities": probabilities, "judgment": judgment})
        );
    }
    Ok(())
}
