//! Benchmark-only resident Native session. One process loads the bundle once, then runs a job
//! of requests in order and emits one JSON line per event.
//!
//!   resident_bench --mode api|internal manifest job.json
//!
//! `api` (the measured boundary for speed comparisons): `pure_jeff::Model::load`, then
//! `Model::decide` per request, which includes the request checks, the byte/token/forward
//! budgets, the deadline, the artifacts and `Observation::validate`. `wall_s` is the time
//! around `decide` only (the request is parsed before). There are no timers inside.
//!
//! `internal` (diagnostic): the library modules called directly (verify, tokenizer, mmap; then
//! prepare, `backbone::forward`, readout, policy) with a timer between the stages. It skips
//! the API checks, so it is not used for speed claims.
//!
//! The job is `[{"name", "phase", "max_input_tokens", "request"}]`; `phase` is copied to the
//! output (warmup, measure, gate). Failures (e.g. a request over the token budget) are
//! reported as decisions with `outcome: failed`; anything else is fatal.
use anyhow::{bail, ensure, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
    DecisionRequest, Judgment, Limits, LoadOptions, Model,
};
use serde_json::{json, Value};
use std::{
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Case {
    name: String,
    phase: String,
    max_input_tokens: usize,
    request: DecisionRequest,
}

const MAX_INPUT_BYTES: usize = 1024 * 1024;

fn limits(case: &Case, deadline: Instant) -> Limits {
    Limits {
        max_input_bytes: MAX_INPUT_BYTES,
        max_input_tokens: case.max_input_tokens,
        max_forwards: 1,
        deadline,
    }
}

fn judgment(value: &Judgment) -> Value {
    serde_json::to_value(value).expect("judgment serializes")
}

/// The CPU features the kernels can use: detected at run time and enabled at compile time.
fn kernel() -> Value {
    #[cfg(target_arch = "x86_64")]
    let detected = json!({
        "avx": std::is_x86_feature_detected!("avx"),
        "avx2": std::is_x86_feature_detected!("avx2"),
        "fma": std::is_x86_feature_detected!("fma"),
        "f16c": std::is_x86_feature_detected!("f16c"),
        "avx512f": std::is_x86_feature_detected!("avx512f"),
        "avxvnni": std::is_x86_feature_detected!("avxvnni"),
    });
    #[cfg(not(target_arch = "x86_64"))]
    let detected = Value::Null;
    json!({
        "detected": detected,
        "compiled": {
            "avx": cfg!(target_feature = "avx"),
            "avx2": cfg!(target_feature = "avx2"),
            "fma": cfg!(target_feature = "fma"),
            "f16c": cfg!(target_feature = "f16c"),
        },
        "candle": {
            "with_avx": candle_core::utils::with_avx(),
            "with_f16c": candle_core::utils::with_f16c(),
            "has_mkl": candle_core::utils::has_mkl(),
            "num_threads": candle_core::utils::get_num_threads(),
        },
    })
}

fn emit(value: Value) {
    println!("{value}");
}

fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        args.len() == 5 && args[1] == "--mode" && (args[2] == "api" || args[2] == "internal"),
        "usage: resident_bench --mode api|internal manifest job.json"
    );
    let (mode, manifest, job) = (&args[2], Path::new(&args[3]), Path::new(&args[4]));
    let deadline = started + Duration::from_secs(4 * 3600);
    let header: Manifest = bundle::read_json(manifest, 2 * 1024 * 1024)?;
    header.policy.validate()?;
    pure_jeff::configure_threads(header.policy.cpu_threads)?;
    let cases: Vec<Case> = bundle::read_json(job, 64 * 1024 * 1024)?;
    let common = json!({
        "event": "init", "mode": mode,
        "compute_threads": candle_core::utils::get_num_threads(),
        "runtime_build": pure_jeff::runtime_build_hash(),
        "source_sha256": bundle::hash_bytes(include_bytes!("resident_bench.rs")),
        "kernel": kernel(),
    });
    if mode == "api" {
        let step = Instant::now();
        let model = Model::load(
            manifest,
            &LoadOptions {
                deadline: Some(deadline),
                require_runtime_build: true,
            },
        )?;
        let mut init = common;
        init["load_s"] = json!(step.elapsed().as_secs_f64());
        init["startup_s"] = json!(started.elapsed().as_secs_f64());
        init["manifest_sha256"] = json!(model.manifest_sha256());
        emit(init);
        for (index, case) in cases.iter().enumerate() {
            let begin = Instant::now();
            let result = model.decide(&case.request, limits(case, deadline));
            let wall_s = begin.elapsed().as_secs_f64();
            let outcome = match result {
                Ok(o) => json!({
                    "status": "completed",
                    "candidate_ids": o.scores.iter().map(|s| &s.candidate_id).collect::<Vec<_>>(),
                    "probabilities": o.scores.iter().map(|s| s.option_probability).collect::<Vec<_>>(),
                    "judgment": judgment(&o.judgment),
                    "input_tokens": o.input_tokens,
                    "forwards": o.forwards,
                    "rendered_prompt_sha256": o.artifacts.iter()
                        .find(|a| a.component == "rendered_prompt").map(|a| &a.sha256),
                }),
                Err(failure) => json!({"status": "failed", "failure": failure}),
            };
            emit(
                json!({"event": "decision", "index": index, "name": case.name,
                "phase": case.phase, "wall_s": wall_s, "outcome": outcome}),
            );
        }
        return Ok(());
    }

    let step = Instant::now();
    let bundle = Bundle::verify(manifest, deadline, true)?;
    let verify_s = step.elapsed().as_secs_f64();
    let step = Instant::now();
    let tokenizer = Tokenizer::load(&bundle)?;
    let tokenizer_s = step.elapsed().as_secs_f64();
    // SAFETY: fixed verified local assets must remain immutable throughout the benchmark.
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
    let mut init = common;
    init["verify_s"] = json!(verify_s);
    init["tokenizer_s"] = json!(tokenizer_s);
    init["startup_s"] = json!(started.elapsed().as_secs_f64());
    init["manifest_sha256"] = json!(bundle.manifest_sha256);
    emit(init);
    for (index, case) in cases.iter().enumerate() {
        let begin = Instant::now();
        let prepared = match tokenizer.prepare(
            &bundle.decision,
            &case.request,
            limits(case, deadline),
        ) {
            Ok(p) => p,
            Err(error) => {
                // The internal path has no typed failures; only budget rejections are expected.
                if case.phase == "measure" {
                    bail!("{}: {error:#}", case.name);
                }
                emit(
                    json!({"event": "decision", "index": index, "name": case.name,
                    "phase": case.phase, "wall_s": begin.elapsed().as_secs_f64(),
                    "outcome": {"status": "failed", "failure": "prepare", "error": format!("{error:#}")}}),
                );
                continue;
            }
        };
        let tokenized = begin.elapsed().as_secs_f64();
        let step = Instant::now();
        let hidden = backbone::forward(&weights, &prepared.ids)?;
        let forward_s = step.elapsed().as_secs_f64();
        let step = Instant::now();
        let probabilities = readout::probabilities(
            &readout_weights,
            &hidden,
            case.request.candidates.len(),
            bundle.decision.temperature,
        )?;
        let decided = bundle
            .manifest
            .policy
            .judge(&case.request, &probabilities)?;
        let readout_s = step.elapsed().as_secs_f64();
        emit(
            json!({"event": "decision", "index": index, "name": case.name, "phase": case.phase,
            "wall_s": begin.elapsed().as_secs_f64(),
            "stages": {"prompt_tokenize_s": tokenized, "forward_s": forward_s,
                       "readout_policy_s": readout_s},
            "outcome": {
                "status": "completed",
                "candidate_ids": case.request.candidates.iter().map(|c| &c.id).collect::<Vec<_>>(),
                "probabilities": probabilities,
                "judgment": judgment(&decided),
                "input_tokens": prepared.ids.len(),
                "forwards": 1,
                "rendered_prompt_sha256": bundle::hash_bytes(prepared.prompt.as_bytes()),
                "input_ids_sha256": bundle::hash_bytes(
                    &prepared.ids.iter().flat_map(|i| i.to_le_bytes()).collect::<Vec<u8>>()),
            }}),
        );
    }
    Ok(())
}
