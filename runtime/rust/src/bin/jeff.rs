//! Rust-only local asset locking, request preparation and native evaluation.
//! Bundles must be locked by this build (`require_runtime_build`), as before the library split.
use anyhow::{ensure, Context, Result};
use pure_jeff::{
    bundle::{self, Bundle},
    evaluate,
    policy::Policy,
    tokenize::Tokenizer,
    ColdProvider, DecisionRequest, Limits, Manifest, NativeProcessProvider,
};
use std::{
    path::Path,
    time::{Duration, Instant},
};
fn main() -> Result<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().collect();
    let command=args.get(1).map(String::as_str).context("usage: jeff lock checkpoint manifest revision min-probability min-margin threads | jeff prepare/decide/decide-process manifest request timeout-ms max-input-tokens | jeff worker --manifest path --request path --response path")?;
    if command == "worker" {
        ensure!(
            args.len() == 8
                && args[2] == "--manifest"
                && args[4] == "--request"
                && args[6] == "--response",
            "invalid worker arguments"
        );
        return pure_jeff::worker::run(
            Path::new(&args[3]),
            Path::new(&args[5]),
            Path::new(&args[7]),
            started,
            true,
        )
        .map_err(Into::into);
    }
    if command == "lock" {
        ensure!(
            args.len() == 8,
            "lock requires checkpoint manifest revision min-probability min-margin threads"
        );
        let policy = Policy {
            min_probability: args[5].parse()?,
            min_margin: args[6].parse()?,
            cpu_threads: args[7].parse()?,
        };
        let manifest_sha256 = pure_jeff::lock(
            Path::new(&args[2]),
            Path::new(&args[3]),
            &args[4],
            policy,
            started + Duration::from_secs(120),
        )?;
        println!(
            "{}",
            serde_json::json!({"schema_version":bundle::SCHEMA,"manifest_sha256":manifest_sha256})
        );
        return Ok(());
    }
    ensure!(
        ["prepare", "decide", "decide-process"].contains(&command) && args.len() == 6,
        "prepare/decide/decide-process requires manifest request timeout-ms max-input-tokens"
    );
    let timeout_ms: u64 = args[4].parse()?;
    ensure!(timeout_ms > 0, "positive timeout required");
    let deadline = started
        .checked_add(Duration::from_millis(timeout_ms))
        .context("timeout overflow")?;
    let limits = Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: args[5].parse()?,
        max_forwards: 1,
        deadline,
    };
    let request: DecisionRequest = bundle::read_json(Path::new(&args[3]), 16 * 1024 * 1024)?;
    request.validate()?;
    if request.reason.is_some() && command != "decide-process" {
        let manifest: Manifest = bundle::read_json(Path::new(&args[2]), 2 * 1024 * 1024)?;
        manifest.policy.validate()?;
        // This one-request CLI sets process-global thread configuration before any inference.
        std::env::set_var("RAYON_NUM_THREADS", manifest.policy.cpu_threads.to_string());
        std::env::set_var(
            "CANDLE_NUM_THREADS",
            manifest.policy.cpu_threads.to_string(),
        );
    }
    if command == "decide-process" && request.reason.is_some() {
        let mut provider = NativeProcessProvider::new(std::env::current_exe()?, &args[2])?;
        let attempt = evaluate(&mut provider, request, limits)?;
        println!("{}", serde_json::to_string(&attempt)?);
    } else if command == "decide" || command == "decide-process" {
        let mut provider = ColdProvider::new(&args[2]).require_runtime_build(true);
        let attempt = evaluate(&mut provider, request, limits)?;
        println!("{}", serde_json::to_string(&attempt)?);
    } else if request.reason.is_none() {
        println!("{}", serde_json::json!({"status":"not_selected"}));
    } else {
        let bundle = Bundle::verify(Path::new(&args[2]), deadline, true)?;
        let tokenizer = Tokenizer::load(&bundle)?;
        let prepared = tokenizer.prepare(&bundle.decision, &request, limits)?;
        println!(
            "{}",
            serde_json::json!({"schema_version":"pure_jeff.prepared.v1","request":request,
            "prompt":prepared.prompt,"input_tokens":prepared.ids.len(),"token_ids":prepared.ids,
            "manifest_sha256":bundle.manifest_sha256,"forwards":0})
        );
    }
    Ok(())
}
