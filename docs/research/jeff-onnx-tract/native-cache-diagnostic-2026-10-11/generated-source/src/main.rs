//! Experimental resident wrapper. Frozen native runtime sources are unchanged.
mod backbone;
mod cache_diagnostic;
mod readout;
mod threads;
mod weights;
use anyhow::{ensure, Result};
use kaze_judge::{DecisionRequest, Limits};
use kaze_judge_jeff::{
    bundle::{Bundle, Manifest},
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
    if args[0] == "--cache-probe" {
        emit(cache_diagnostic::initialize(args[1].parse()?)?)?;
        return Ok(());
    }
    let deadline = started + Duration::from_secs(600);
    let job: Value = serde_json::from_slice(&fs::read(&args[1])?)?;
    let header: Manifest = serde_json::from_slice(&fs::read(&args[0])?)?;
    ensure!(header.policy.cpu_threads == 1, "pilot requires one thread");
    let cache_diagnostic = cache_diagnostic::initialize(
        job["cache_init_cpu"]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("cache_init_cpu required"))? as usize,
    )?;
    let requested_threads = threads::configure(&job)?;
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
    let retained = job["retained_f32"]
        .as_bool()
        .ok_or_else(|| anyhow::anyhow!("retained_f32 required"))?;
    let check_load = || {
        if Instant::now() >= deadline {
            candle_core::bail!("load deadline exceeded")
        } else {
            Ok(())
        }
    };
    let step = Instant::now();
    let weights = weights::Weights::from_mapped(weights, retained, &check_load)?;
    let head_weights = if retained {
        // SAFETY: parent freezes the verified readout file for the experiment.
        let head = unsafe {
            candle_core::safetensors::MmapedSafetensors::new(
                bundle.root.join("readout.safetensors"),
            )?
        };
        Some(weights::Weights::from_mapped(head, true, &check_load)?)
    } else {
        None
    };
    let retention_load_ns = step.elapsed().as_nanos();
    let (cached_tensors, cached_bytes) = weights.retained_size();
    let (head_cached_tensors, head_cached_bytes) =
        head_weights.as_ref().map_or((0, 0), |w| w.retained_size());
    emit(
        json!({"event":"initialized","backend":"native","cache_diagnostic":cache_diagnostic,"verify_ns":verify_ns,
        "tokenizer_load_ns":tokenizer_load_ns,"mmap_ns":mmap_ns,"startup_ns":started.elapsed().as_nanos(),
        "threads":candle_core::utils::get_num_threads(),"requested_threads":requested_threads,"rayon_pool_threads":rayon::current_num_threads(),"candle_env_threads":std::env::var("CANDLE_NUM_THREADS")?,"expected_barrier_aux_workers":requested_threads-1,"manifest_cpu_threads":header.policy.cpu_threads,"retained_f32":retained,"retention_load_ns":retention_load_ns,"cached_tensors":cached_tensors,"cached_bytes":cached_bytes,"head_cached_tensors":head_cached_tensors,"head_cached_bytes":head_cached_bytes}),
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
        let processor_before = cache_diagnostic::processor();
        let hidden = backbone::forward_checked(&weights, &prepared.ids, &check)?;
        let backbone_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        let (probabilities, raw_logits) = if let Some(head) = &head_weights {
            readout::probabilities(
                head,
                &hidden,
                request.candidates.len(),
                bundle.decision.temperature,
            )?
        } else {
            anyhow::bail!("diagnostic requires retained head")
        };
        let head_softmax_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        let judgment = bundle.manifest.policy.judge(&request, &probabilities)?;
        let policy_ns = step.elapsed().as_nanos();
        let processor_after = cache_diagnostic::processor();
        let hidden_values = hidden.flatten_all()?.to_vec1::<f32>()?;
        emit(
            json!({"input_ids":prepared.ids,"hidden_values":hidden_values,"raw_logits":raw_logits,
            "processor_before":processor_before,"processor_after":processor_after,"event":"request","case":case["id"],"iteration":iteration,"warmup":item["warmup"],
            "effective_tokens":prepared.ids.len(),"physical_tokens":prepared.ids.len(),"tokenize_ns":tokenize_ns,
            "backbone_ns":backbone_ns,"head_softmax_ns":head_softmax_ns,"policy_ns":policy_ns,
            "request_ns":request_started.elapsed().as_nanos(),"probabilities":probabilities,"judgment":judgment}),
        )?;
    }
    emit(json!({"event":"completed","total_ns":started.elapsed().as_nanos()}))?;
    Ok(())
}
