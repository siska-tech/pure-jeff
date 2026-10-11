//! Experimental resident wrapper. Frozen native runtime sources are unchanged.
use anyhow::{ensure, Result};
use kaze_judge::{DecisionRequest, Limits};
use kaze_judge_jeff::{
    backbone,
    bundle::{Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::Path,
    time::{Duration, Instant},
};

fn emit(value: Value) -> Result<()> {
    println!("{value}");
    std::io::stdout().flush()?;
    Ok(())
}

fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().skip(1).collect();
    ensure!(args.len() == 2, "usage: native_bench manifest job.json");
    let deadline = started + Duration::from_secs(600);
    let job: Value = serde_json::from_slice(&fs::read(&args[1])?)?;
    let header: Manifest = serde_json::from_slice(&fs::read(&args[0])?)?;
    ensure!(header.policy.cpu_threads == 1, "pilot requires one thread");
    std::env::set_var("CANDLE_NUM_THREADS", "1");
    std::env::set_var("RAYON_NUM_THREADS", "1");
    let step = Instant::now();
    let bundle = Bundle::verify(Path::new(&args[0]), deadline)?;
    let verify_ns = step.elapsed().as_nanos();
    let step = Instant::now();
    let tokenizer = Tokenizer::load(&bundle)?;
    let tokenizer_load_ns = step.elapsed().as_nanos();
    let step = Instant::now();
    // SAFETY: parent verifies fixed assets and prohibits mutations during the experiment.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    let mmap_ns = step.elapsed().as_nanos();
    emit(
        json!({"event":"initialized","backend":"native","verify_ns":verify_ns,
        "tokenizer_load_ns":tokenizer_load_ns,"mmap_ns":mmap_ns,"startup_ns":started.elapsed().as_nanos(),
        "threads":candle_core::utils::get_num_threads(),"retained":"tokenizer and BF16 mmap; FP32 conversion remains per forward"}),
    )?;
    let cases = job["cases"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing cases"))?;
    for (iteration, item) in job["schedule"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing schedule"))?
        .iter()
        .enumerate()
    {
        let request_started = Instant::now();
        let index = item["case"]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("invalid case"))? as usize;
        let case = cases
            .get(index)
            .ok_or_else(|| anyhow::anyhow!("case out of range"))?;
        let request: DecisionRequest = serde_json::from_value(case["request"].clone())?;
        let step = Instant::now();
        let prepared = tokenizer.prepare(
            &bundle,
            &request,
            Limits {
                max_input_bytes: 1024 * 1024,
                max_input_tokens: 512,
                max_forwards: 1,
                deadline,
            },
        )?;
        let tokenize_ns = step.elapsed().as_nanos();
        let check = || {
            if Instant::now() >= deadline {
                candle_core::bail!("deadline exceeded")
            } else {
                Ok(())
            }
        };
        let step = Instant::now();
        let hidden = backbone::forward_checked(&weights, &prepared.ids, &check)?;
        let backbone_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        let probabilities = readout::probabilities(
            &bundle.root,
            &hidden,
            request.candidates.len(),
            bundle.decision.temperature,
        )?;
        let head_softmax_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        let judgment = bundle.manifest.policy.judge(&request, &probabilities)?;
        let policy_ns = step.elapsed().as_nanos();
        emit(
            json!({"event":"request","case":case["id"],"iteration":iteration,"warmup":item["warmup"],
            "effective_tokens":prepared.ids.len(),"physical_tokens":prepared.ids.len(),"tokenize_ns":tokenize_ns,
            "backbone_ns":backbone_ns,"head_softmax_ns":head_softmax_ns,"policy_ns":policy_ns,
            "request_ns":request_started.elapsed().as_nanos(),"probabilities":probabilities,"judgment":judgment}),
        )?;
    }
    emit(json!({"event":"completed","total_ns":started.elapsed().as_nanos()}))?;
    Ok(())
}
