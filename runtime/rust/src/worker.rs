//! One request per process. No subprocesses or network operations.
use crate::{bundle, RustProvider};
use anyhow::{ensure, Result};
use kaze_judge::{DecisionProvider, DecisionRequest, Failure, Limits, Observation};
use serde::{Deserialize, Serialize};
use std::{
    fs::OpenOptions,
    io::Write,
    path::Path,
    time::{Duration, Instant},
};
const SCHEMA: &str = "kaze_judge.worker.v1";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WireRequest {
    schema_version: String,
    request: DecisionRequest,
    max_input_tokens: usize,
    max_forwards: usize,
    timeout_ms: u64,
}
#[derive(Serialize)]
struct WireResponse<'a> {
    schema_version: &'static str,
    request_id: &'a str,
    result: WorkerResult,
}
#[derive(Serialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
enum WorkerResult {
    Completed(Observation),
    Failed(Failure),
}
pub fn run(manifest: &Path, input: &Path, output: &Path, started: Instant) -> Result<()> {
    let wire: WireRequest = bundle::read_json(input, 2 * 1024 * 1024)?;
    ensure!(wire.schema_version == SCHEMA, "unsupported worker schema");
    wire.request.validate()?;
    let deadline = started
        .checked_add(Duration::from_millis(wire.timeout_ms))
        .ok_or_else(|| anyhow::anyhow!("timeout overflow"))?;
    let limits = Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: wire.max_input_tokens,
        max_forwards: wire.max_forwards,
        deadline,
    };
    let infer = || -> std::result::Result<Observation, Failure> {
        if wire.request.reason.is_none() {
            return Err(Failure::InvalidRequest);
        }
        if serde_json::to_vec(&wire.request)
            .map_err(|_| Failure::InvalidRequest)?
            .len()
            > limits.max_input_bytes
            || limits.max_forwards == 0
            || limits.max_input_tokens == 0
        {
            return Err(Failure::BudgetExceeded);
        }
        if Instant::now() >= deadline {
            return Err(Failure::Timeout);
        }
        let header: bundle::Manifest =
            bundle::read_json(manifest, 2 * 1024 * 1024).map_err(|_| Failure::Unavailable)?;
        header.policy.validate().map_err(|_| Failure::Unavailable)?;
        std::env::set_var("RAYON_NUM_THREADS", header.policy.cpu_threads.to_string());
        std::env::set_var("CANDLE_NUM_THREADS", header.policy.cpu_threads.to_string());
        RustProvider::new(manifest).decide(&wire.request, limits)
    };
    let result = infer();
    let result = if Instant::now() >= deadline {
        WorkerResult::Failed(Failure::Timeout)
    } else {
        match result {
            Ok(observation) => WorkerResult::Completed(observation),
            Err(failure) => WorkerResult::Failed(failure),
        }
    };
    let bytes = serde_json::to_vec(&WireResponse {
        schema_version: SCHEMA,
        request_id: &wire.request.request_id,
        result,
    })?;
    ensure!(bytes.len() <= 1024 * 1024, "response size limit exceeded");
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?
        .write_all(&bytes)?;
    Ok(())
}
