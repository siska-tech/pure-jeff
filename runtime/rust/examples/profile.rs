//! Diagnostic one-shot stage timings. Not a worker protocol or warm model service.
use anyhow::{ensure, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
};
use pure_jeff::{DecisionRequest, Limits};
use std::{
    collections::BTreeMap,
    path::Path,
    time::{Duration, Instant},
};
fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: profile manifest request");
    let deadline = started + Duration::from_secs(120);
    let header: Manifest = bundle::read_json(Path::new(&args[1]), 2 * 1024 * 1024)?;
    header.policy.validate()?;
    std::env::set_var("RAYON_NUM_THREADS", header.policy.cpu_threads.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", header.policy.cpu_threads.to_string());
    let request: DecisionRequest = bundle::read_json(Path::new(&args[2]), 1024 * 1024)?;
    let mut timings = BTreeMap::new();
    timings.insert("request_and_header", started.elapsed().as_secs_f64());
    let step = Instant::now();
    let bundle = Bundle::verify(Path::new(&args[1]), deadline, true)?;
    timings.insert(
        "bundle_hash_and_metadata_validation",
        step.elapsed().as_secs_f64(),
    );
    let step = Instant::now();
    let tokenizer = Tokenizer::load(&bundle)?;
    timings.insert(
        "tokenizer_load_and_vocabulary_validation",
        step.elapsed().as_secs_f64(),
    );
    let step = Instant::now();
    let prepared = tokenizer.prepare(
        &bundle.decision,
        &request,
        Limits {
            max_input_bytes: 1024 * 1024,
            max_input_tokens: 8192,
            max_forwards: 1,
            deadline,
        },
    )?;
    timings.insert("prompt_and_tokenize", step.elapsed().as_secs_f64());
    let step = Instant::now();
    // SAFETY: fixed verified local assets must remain immutable throughout profiling.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    // SAFETY: as above.
    let readout_weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("readout.safetensors"))?
    };
    timings.insert("model_mmap", step.elapsed().as_secs_f64());
    let step = Instant::now();
    let hidden = backbone::forward_checked(&weights, &prepared.ids, &|| {
        if Instant::now() >= deadline {
            candle_core::bail!("deadline exceeded");
        }
        Ok(())
    })?;
    timings.insert(
        "forward_including_weight_conversion",
        step.elapsed().as_secs_f64(),
    );
    let step = Instant::now();
    let probabilities = readout::probabilities(
        &readout_weights,
        &hidden,
        request.candidates.len(),
        bundle.decision.temperature,
    )?;
    let judgment = bundle.manifest.policy.judge(&request, &probabilities)?;
    timings.insert("readout_and_policy", step.elapsed().as_secs_f64());
    bundle::check_time(deadline)?;
    println!(
        "{}",
        serde_json::json!({"schema_version":"kaze_judge.profile.v1",
        "timings_seconds":timings,"total_seconds":started.elapsed().as_secs_f64(),
        "input_tokens":prepared.ids.len(),"forwards":1,"probabilities":probabilities,"judgment":judgment,
        "runtime_build_sha256":bundle.manifest.runtime_build_sha256,
        "profiler_source_sha256":bundle::hash_bytes(include_bytes!("profile.rs"))})
    );
    Ok(())
}
