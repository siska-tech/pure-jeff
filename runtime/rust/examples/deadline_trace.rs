//! Diagnostic (#18): how long the steps between deadline checks of the forward take on a host.
//! The forward runs with a `check` that records the time of every call (before the embedding,
//! before each of the 24 layers, between the query blocks of full attention) and, like
//! `Model::decide`, fails once the deadline has passed.
//!
//!   deadline_trace <manifest> <request.json> <deadline seconds|none>
//!
//! Prints one JSON line: the load and prepare times, every check (seconds since the forward
//! started, and the step that follows it), the check that saw the expired deadline, and the time
//! the forward returned.
use anyhow::{Context, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    tokenize::Tokenizer,
    DecisionRequest, Limits,
};
use serde_json::json;
use std::{
    cell::RefCell,
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Wrapped {
    request: DecisionRequest,
}

fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [manifest, path, seconds] = args.as_slice() else {
        anyhow::bail!("usage: deadline_trace <manifest> <request.json> <deadline seconds|none>")
    };
    let budget = (seconds != "none")
        .then(|| seconds.parse::<f64>().map(Duration::from_secs_f64))
        .transpose()
        .context("seconds")?;
    let far = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    pure_jeff::configure_threads(header.policy.cpu_threads)?;
    let bundle = Bundle::verify(Path::new(manifest), far, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    let load_s = started.elapsed().as_secs_f64();
    let text = std::fs::read_to_string(path)?;
    let request = serde_json::from_str::<Wrapped>(&text)
        .map(|w| w.request)
        .or_else(|_| serde_json::from_str::<DecisionRequest>(&text))?;
    let limits = Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: 8192,
        max_forwards: 1,
        deadline: far,
    };
    let step = Instant::now();
    let ids = tokenizer.prepare(&bundle.decision, &request, limits)?.ids;
    let prepare_s = step.elapsed().as_secs_f64();
    let forward_started = Instant::now();
    let deadline = budget.map(|b| forward_started + b);
    let checks = RefCell::new(Vec::<f64>::new());
    let expired_at = RefCell::new(None::<f64>);
    let check = || -> candle_core::Result<()> {
        let now = forward_started.elapsed().as_secs_f64();
        checks.borrow_mut().push(now);
        if deadline.is_some_and(|d| Instant::now() >= d) {
            *expired_at.borrow_mut() = Some(now);
            candle_core::bail!("deadline")
        }
        Ok(())
    };
    let result = backbone::forward_blocks(&weights, &ids, &check, true, backbone::QUERY_BLOCK);
    let returned_s = forward_started.elapsed().as_secs_f64();
    let checks = checks.into_inner();
    let longest = checks
        .windows(2)
        .map(|w| w[1] - w[0])
        .chain(
            result
                .is_ok()
                .then(|| returned_s - checks.last().copied().unwrap_or(0.0)),
        )
        .fold(0f64, f64::max);
    println!(
        "{}",
        json!({"tokens": ids.len(), "threads": candle_core::utils::get_num_threads(),
            "deadline_s": budget.map(|b| b.as_secs_f64()), "load_s": load_s, "prepare_s": prepare_s,
            "checks_s": checks, "longest_step_s": longest, "expired_check_s": expired_at.into_inner(),
            "forward_returned_s": returned_s, "completed": result.is_ok()})
    );
    Ok(())
}
