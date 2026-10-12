//! Browser demo engine on [`pure_jeff::memory`]: the library verifies the in-memory assets and
//! makes each decision (bundle checks, prompt, forward, readout, policy, artifacts, `Attempt`
//! semantics). This crate adds what is specific to the page: the deployment's expected manifest
//! hash, the engine's own hash as the runtime artifact, digests computed while assets stream in,
//! the 512-token range validated in the browser and stage timings. The page owns the time
//! limit: it cancels by terminating the Worker.
use anyhow::{ensure, Result};
use pure_jeff::{memory, Artifact, Attempt, DecisionRequest, Failure};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[cfg(target_arch = "wasm32")]
mod wasm;

/// Input range validated in the browser (W2); longer prompts are rejected, not truncated.
pub const MAX_INPUT_TOKENS: usize = 512;
/// Asset slots, in the order the page loads them.
pub const ASSET_PATHS: [&str; 4] = memory::ASSET_FILES;

pub fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Milliseconds from an arbitrary origin; the page supplies the clock on wasm32.
pub fn now_ms() -> f64 {
    #[cfg(target_arch = "wasm32")]
    {
        wasm::now_ms()
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        use std::{sync::OnceLock, time::Instant};
        static START: OnceLock<Instant> = OnceLock::new();
        START.get_or_init(Instant::now).elapsed().as_secs_f64() * 1000.0
    }
}

/// SHA-256 over one asset, fed in order while it streams into memory.
pub struct StreamHash {
    hasher: Sha256,
    len: usize,
    next: usize,
}

impl StreamHash {
    pub fn new(len: usize) -> Self {
        Self {
            hasher: Sha256::new(),
            len,
            next: 0,
        }
    }
    /// `offset` must continue exactly where the previous chunk ended.
    pub fn update(&mut self, offset: usize, chunk: &[u8]) -> Result<()> {
        ensure!(
            offset == self.next && offset + chunk.len() <= self.len,
            "out-of-order hash update"
        );
        self.hasher.update(chunk);
        self.next += chunk.len();
        Ok(())
    }
    /// Digest only when every byte of the asset was hashed.
    pub fn finish(self) -> Option<String> {
        (self.next == self.len).then(|| format!("{:x}", self.hasher.finalize()))
    }
}

/// Bytes the page keeps allocated and unchanged while the session exists.
pub struct Assets<'a> {
    pub manifest: &'a [u8],
    /// In `ASSET_PATHS` order.
    pub files: [&'a [u8]; 4],
}

pub struct Session<'a> {
    inner: memory::Session<'a>,
}

impl<'a> Session<'a> {
    /// Verifies the manifest against the deployment's expected hash, then lets the library
    /// verify every asset against the manifest (using streamed digests when complete, hashing
    /// otherwise), the decision config and the tokenizer's answer vocabulary.
    pub fn open(
        assets: &Assets<'a>,
        streamed: [Option<String>; 4],
        expected_manifest_sha256: &str,
        engine_sha256: &str,
    ) -> Result<(Self, Value)> {
        let started = now_ms();
        ensure!(
            sha256(assets.manifest) == expected_manifest_sha256,
            "bundle manifest hash mismatch"
        );
        ensure!(
            engine_sha256.len() == 64 && engine_sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid engine hash"
        );
        let mut hashed = started;
        let (inner, hashed_now) = memory::Session::open_with(
            &memory::Assets {
                manifest: assets.manifest,
                files: assets.files,
            },
            streamed,
            // As Native, except that this module replaces the Native `runtime_build`.
            Artifact {
                component: "wasm_engine".into(),
                sha256: engine_sha256.to_owned(),
            },
            &mut |stage| {
                if stage == "hash" {
                    hashed = now_ms();
                }
            },
        )?;
        let report = json!({
            "hash_ms": hashed - started,
            "tokenizer_ms": now_ms() - hashed,
            "hashed_at_open": hashed_now,
            "checkpoint_revision": inner.manifest().checkpoint_revision,
        });
        Ok((Self { inner }, report))
    }

    /// `pure_jeff::evaluate` semantics without a clock, within at most `MAX_INPUT_TOKENS`, with
    /// the milliseconds of each decision stage.
    pub fn evaluate(
        &self,
        request: DecisionRequest,
        max_input_bytes: usize,
        max_input_tokens: usize,
    ) -> Result<(Attempt, Vec<Value>), Failure> {
        let mut stages = Vec::new();
        let mut last = now_ms();
        let attempt = self.inner.evaluate(
            request,
            max_input_bytes,
            max_input_tokens.min(MAX_INPUT_TOKENS),
            &mut |name| {
                let now = now_ms();
                stages.push(json!({"name": name, "ms": now - last}));
                last = now;
            },
        )?;
        Ok((attempt, stages))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn streamed_digest_equals_one_shot_digest() {
        let data: Vec<u8> = (0..10_000u32).map(|i| (i * 31 % 251) as u8).collect();
        let mut stream = StreamHash::new(data.len());
        for (i, chunk) in data.chunks(777).enumerate() {
            stream.update(i * 777, chunk).unwrap();
        }
        assert_eq!(stream.finish(), Some(sha256(&data)));
    }

    #[test]
    fn out_of_order_or_partial_streams_give_no_digest() {
        let data = [7u8; 100];
        let mut skipped = StreamHash::new(100);
        assert!(skipped.update(10, &data[10..20]).is_err());
        let mut overflow = StreamHash::new(100);
        assert!(overflow.update(0, &[0u8; 101]).is_err());
        let mut partial = StreamHash::new(100);
        partial.update(0, &data[..50]).unwrap();
        assert_eq!(partial.finish(), None);
    }

    #[test]
    fn a_wrong_manifest_or_engine_hash_is_rejected_before_parsing() {
        let assets = Assets {
            manifest: b"{}",
            files: [b"", b"", b"", b""],
        };
        let open = |expected: &str, engine: &str| {
            Session::open(&assets, [None, None, None, None], expected, engine)
                .err()
                .unwrap()
                .to_string()
        };
        assert_eq!(open(&"0".repeat(64), &"0".repeat(64)), "bundle manifest hash mismatch");
        assert_eq!(open(&sha256(b"{}"), "short"), "invalid engine hash");
    }
}
