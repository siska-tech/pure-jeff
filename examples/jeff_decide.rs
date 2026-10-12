//! Explicit one-request local smoke runner; no automatic model acquisition.
use pure_jeff::{evaluate, DecisionRequest, Limits, LocalProcessProvider};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 5 {
        return Err("usage: jeff_decide <python.exe> <manifest.json> <request.json> <timeout-ms> <max-input-tokens>".into());
    }
    let timeout: u64 = args[3].to_str().ok_or("invalid timeout")?.parse()?;
    let tokens: usize = args[4].to_str().ok_or("invalid token limit")?.parse()?;
    if timeout == 0 || tokens == 0 {
        return Err("positive timeout and token limit required".into());
    }
    let request: DecisionRequest = serde_json::from_slice(&std::fs::read(&args[2])?)?;
    let worker = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("runtime/jeff_worker.py");
    let mut provider = LocalProcessProvider::new(&args[0], worker, &args[1])?;
    let deadline = Instant::now()
        .checked_add(Duration::from_millis(timeout))
        .ok_or("timeout overflow")?;
    let attempt = evaluate(
        &mut provider,
        request,
        Limits {
            max_input_bytes: 65_536,
            max_input_tokens: tokens,
            max_forwards: 1,
            deadline,
        },
    )?;
    println!("{}", serde_json::to_string_pretty(&attempt)?);
    Ok(())
}
