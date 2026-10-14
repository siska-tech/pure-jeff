//! Diagnostic: the final hidden state with a given number of query rows per attention block,
//! as a SHA-256 of its F32 bits, with the forward time. `max` runs every sequence as one block
//! (the computation before blocks were introduced). Run once per block size, each in its own
//! process, and compare the digests (and the process peaks measured outside).
//!
//!   cargo run --release --example attention_blocks -- <manifest> <block|max> <request.json>...
use anyhow::{Context, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    tokenize::Tokenizer,
    DecisionRequest, Limits,
};
use sha2::{Digest, Sha256};
use std::{
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Wrapped {
    request: DecisionRequest,
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [manifest, block, paths @ ..] = args.as_slice() else {
        anyhow::bail!("usage: attention_blocks <manifest> <block|max> <request.json>...")
    };
    let block = if block == "max" {
        usize::MAX
    } else {
        block.parse().context("block")?
    };
    let deadline = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    pure_jeff::configure_threads(header.policy.cpu_threads)?;
    let bundle = Bundle::verify(Path::new(manifest), deadline, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    for path in paths {
        let text = std::fs::read_to_string(path)?;
        let request = serde_json::from_str::<Wrapped>(&text)
            .map(|w| w.request)
            .or_else(|_| serde_json::from_str::<DecisionRequest>(&text))?;
        let ids = tokenizer
            .prepare(
                &bundle.decision,
                &request,
                Limits {
                    max_input_bytes: 1024 * 1024,
                    max_input_tokens: 8192,
                    max_forwards: 1,
                    deadline,
                },
            )?
            .ids;
        let started = Instant::now();
        let hidden = backbone::forward_blocks(&weights, &ids, &|| Ok(()), true, block)?;
        let forward_s = started.elapsed().as_secs_f64();
        let bytes: Vec<u8> = hidden
            .flatten_all()?
            .to_vec1::<f32>()?
            .iter()
            .flat_map(|v| v.to_bits().to_le_bytes())
            .collect();
        println!(
            "{}",
            serde_json::json!({"request": path, "tokens": ids.len(), "block": block.min(1 << 40),
                "forward_s": forward_s, "hidden_sha256": format!("{:x}", Sha256::digest(&bytes))})
        );
    }
    Ok(())
}
