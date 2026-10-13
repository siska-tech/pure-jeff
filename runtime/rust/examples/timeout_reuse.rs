//! Diagnostic: a decision whose deadline passes inside the forward (between attention blocks
//! or layers) fails with `Timeout`, and the same `Model` then decides another request with
//! bitwise the same probabilities as before the timeout.
//!
//!   cargo run --release --example timeout_reuse -- <manifest> <long request> <short request> <seconds>
use anyhow::{ensure, Context, Result};
use pure_jeff::{DecisionRequest, Failure, Limits, LoadOptions, Model};
use std::time::{Duration, Instant};

#[derive(serde::Deserialize)]
struct Wrapped {
    request: DecisionRequest,
}

fn read(path: &str) -> Result<DecisionRequest> {
    let text = std::fs::read_to_string(path)?;
    Ok(serde_json::from_str::<Wrapped>(&text)
        .map(|w| w.request)
        .or_else(|_| serde_json::from_str::<DecisionRequest>(&text))?)
}

fn limits(seconds: f64) -> Limits {
    Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: 8192,
        max_forwards: 1,
        deadline: Instant::now() + Duration::from_secs_f64(seconds),
    }
}

fn bits(o: &pure_jeff::Observation) -> Vec<u64> {
    o.scores
        .iter()
        .map(|s| s.option_probability.to_bits())
        .collect()
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [manifest, long, short, seconds] = args.as_slice() else {
        anyhow::bail!("usage: timeout_reuse <manifest> <long> <short> <seconds>")
    };
    let seconds: f64 = seconds.parse().context("seconds")?;
    let manifest_json: pure_jeff::Manifest =
        serde_json::from_str(&std::fs::read_to_string(manifest)?)?;
    pure_jeff::configure_threads(manifest_json.policy.cpu_threads)?;
    let model = Model::load(manifest, &LoadOptions::default())?;
    let (long, short) = (read(long)?, read(short)?);
    let before = model.decide(&short, limits(600.0))?;
    let started = Instant::now();
    let timed_out = model.decide(&long, limits(seconds));
    let stopped_after = started.elapsed().as_secs_f64();
    ensure!(
        timed_out == Err(Failure::Timeout),
        "expected a timeout, got {timed_out:?}"
    );
    let after = model.decide(&short, limits(600.0))?;
    ensure!(
        bits(&before) == bits(&after) && before.judgment == after.judgment,
        "the decision after the timeout differs"
    );
    println!(
        "{}",
        serde_json::json!({"deadline_s": seconds, "stopped_after_s": stopped_after,
            "timeout": true, "reuse_bitwise_equal": true})
    );
    Ok(())
}
