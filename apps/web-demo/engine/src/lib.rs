//! Browser demo engine. Mirrors the Native `RustProvider` (bundle checks, prompt, forward,
//! readout, policy, artifacts) and `kaze_judge::evaluate` (Attempt semantics) on assets held
//! in browser memory. The page owns the time limit: it cancels by terminating the Worker.
use anyhow::{ensure, Context, Result};
use candle_core::safetensors::SliceSafetensors;
use kaze_judge::{
    Artifact, Attempt, CandidateScore, DecisionRequest, Failure, Observation, Outcome,
};
use kaze_judge_wasm_probe::{now_ms, policy::Policy, prompt, slice, tokenize};
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

#[cfg(target_arch = "wasm32")]
mod wasm;

/// Input range validated in the browser (W2); longer prompts are rejected, not truncated.
pub const MAX_INPUT_TOKENS: usize = 512;
/// Asset slots, in the order the page loads them.
pub const ASSET_PATHS: [&str; 4] = [
    "decision_config.json",
    "tokenizer.json",
    "readout.safetensors",
    "model.safetensors",
];

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
#[allow(dead_code)]
struct Manifest {
    schema_version: String,
    checkpoint_dir: String,
    checkpoint_revision: String,
    files: Vec<FileRecord>,
    policy: Policy,
    prompt_sha256: String,
    runtime_build_sha256: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FileRecord {
    path: String,
    sha256: String,
}

/// Same fields and checks as the Native bundle's DecisionConfig.
#[derive(Deserialize)]
struct DecisionConfig {
    format_version: u32,
    base_model: String,
    revision: String,
    codes: Vec<String>,
    token_ids: Vec<u32>,
    temperature: f64,
    #[serde(default = "default_layout")]
    prompt_layout: String,
}

fn default_layout() -> String {
    "state-first".into()
}

impl DecisionConfig {
    fn validate(&self) -> Result<()> {
        ensure!(
            self.format_version == 1
                && self.base_model == "Qwen/Qwen3.5-0.8B"
                && self.revision.len() == 40
                && self.revision.bytes().all(|b| b.is_ascii_hexdigit()),
            "unsupported decision config"
        );
        ensure!(
            self.codes.len() == 255
                && self.token_ids.len() == 255
                && self.codes.iter().all(|c| !c.trim().is_empty())
                && self.codes.iter().collect::<HashSet<_>>().len() == 255
                && self.token_ids.iter().collect::<HashSet<_>>().len() == 255,
            "invalid answer vocabulary"
        );
        ensure!(
            self.temperature.is_finite()
                && self.temperature > 0.0
                && ["state-first", "live-last"].contains(&self.prompt_layout.as_str()),
            "invalid temperature/layout"
        );
        Ok(())
    }
}

pub fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
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
    manifest: Manifest,
    manifest_sha256: String,
    engine_sha256: String,
    config: DecisionConfig,
    tokenizer: tokenize::Loaded,
    readout: &'a [u8],
    model: &'a [u8],
}

impl<'a> Session<'a> {
    /// Verifies the manifest against the deployment's expected hash, every asset against the
    /// manifest (using streamed digests when complete, hashing otherwise), the decision config
    /// and the tokenizer's answer vocabulary.
    pub fn open(
        assets: &Assets<'a>,
        streamed: [Option<String>; 4],
        expected_manifest_sha256: &str,
        engine_sha256: &str,
    ) -> Result<(Self, Value)> {
        let started = now_ms();
        let manifest_sha256 = sha256(assets.manifest);
        ensure!(
            manifest_sha256 == expected_manifest_sha256,
            "bundle manifest hash mismatch"
        );
        let manifest: Manifest = serde_json::from_slice(assets.manifest)?;
        ensure!(
            manifest.schema_version == "kaze_judge.rust_jeff_bundle.v1",
            "unsupported manifest"
        );
        manifest.policy.validate()?;
        ensure!(
            candle_core::utils::get_num_threads() == manifest.policy.cpu_threads,
            "compute threads differ from the bundle policy"
        );
        ensure!(
            engine_sha256.len() == 64 && engine_sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid engine hash"
        );
        let mut hashed_now = Vec::new();
        for ((path, bytes), digest) in ASSET_PATHS.iter().zip(assets.files).zip(streamed) {
            let record = manifest
                .files
                .iter()
                .find(|f| f.path == *path)
                .with_context(|| format!("{path} missing from manifest"))?;
            let digest = match digest {
                Some(digest) => digest,
                None => {
                    hashed_now.push(*path);
                    sha256(bytes)
                }
            };
            ensure!(digest == record.sha256, "{path} hash mismatch");
        }
        let hashed = now_ms();
        let config: DecisionConfig = serde_json::from_slice(assets.files[0])?;
        config.validate()?;
        let tokenizer = tokenize::load(assets.files[1])?;
        ensure!(
            tokenizer.codes == config.codes
                && tokenizer.ids == config.token_ids
                && tokenizer.single_token_after_prefix,
            "answer vocabulary differs from tokenizer"
        );
        let report = json!({
            "hash_ms": hashed - started,
            "tokenizer_ms": now_ms() - hashed,
            "hashed_at_open": hashed_now,
            "checkpoint_revision": manifest.checkpoint_revision,
        });
        let session = Self {
            manifest,
            manifest_sha256,
            engine_sha256: engine_sha256.to_owned(),
            config,
            tokenizer,
            readout: assets.files[2],
            model: assets.files[3],
        };
        Ok((session, report))
    }

    /// Native `RustProvider::decide` steps; failures map to the same `Failure` kinds.
    fn decide(
        &self,
        request: &DecisionRequest,
        max_input_tokens: usize,
        stages: &mut Vec<Value>,
    ) -> Result<Observation, Failure> {
        request.validate()?;
        if request.reason.is_none()
            || request.question_id != prompt::QUESTION_ID
            || request.candidates.len() > 255
        {
            return Err(Failure::InvalidRequest);
        }
        let mut last = now_ms();
        let mut stage = |name: &str| {
            let now = now_ms();
            stages.push(json!({"name": name, "ms": now - last}));
            last = now;
        };
        let config = &self.config;
        let rendered = prompt::render(request, &config.codes, &config.prompt_layout)
            .map_err(|_| Failure::InvalidRequest)?;
        let ids = self
            .tokenizer
            .encode(&rendered)
            .map_err(|_| Failure::Unavailable)?;
        if ids.is_empty() || ids.len() > max_input_tokens.min(8192) {
            return Err(Failure::BudgetExceeded);
        }
        stage("prompt_tokenize");
        let weights = SliceSafetensors::new(self.model).map_err(|_| Failure::Unavailable)?;
        let hidden = slice::backbone::forward(&weights, &ids).map_err(|_| Failure::Unavailable)?;
        stage("forward");
        let probabilities = slice::readout::probabilities(
            self.readout,
            &hidden,
            request.candidates.len(),
            config.temperature,
        )
        .map_err(|_| Failure::Unavailable)?;
        let judgment = self
            .manifest
            .policy
            .judge(request, &probabilities)
            .map_err(|_| Failure::InvalidOutput)?;
        stage("readout_policy");
        let mut artifacts: Vec<_> = self
            .manifest
            .files
            .iter()
            .map(|r| Artifact {
                component: r.path.clone(),
                sha256: r.sha256.clone(),
            })
            .collect();
        let policy = serde_json::to_vec(&self.manifest.policy).map_err(|_| Failure::Unavailable)?;
        // As Native, except `wasm_engine` (this module) replaces the Native `runtime_build`.
        for (component, sha) in [
            ("bundle_manifest", self.manifest_sha256.clone()),
            ("wasm_engine", self.engine_sha256.clone()),
            ("prompt", self.manifest.prompt_sha256.clone()),
            ("rendered_prompt", sha256(rendered.as_bytes())),
            ("policy", sha256(&policy)),
        ] {
            artifacts.push(Artifact {
                component: component.into(),
                sha256: sha,
            });
        }
        Ok(Observation {
            scores: request
                .candidates
                .iter()
                .zip(probabilities)
                .map(|(c, p)| CandidateScore {
                    candidate_id: c.id.clone(),
                    option_probability: p,
                })
                .collect(),
            judgment,
            temperature: config.temperature,
            input_tokens: ids.len(),
            forwards: 1,
            artifacts,
        })
    }

    /// `kaze_judge::evaluate` semantics without a clock: an invalid request is an error;
    /// no routing reason means no provider call; failures never become judgments.
    pub fn evaluate(
        &self,
        request: DecisionRequest,
        max_input_bytes: usize,
        max_input_tokens: usize,
    ) -> Result<(Attempt, Vec<Value>), Failure> {
        request.validate()?;
        let max_input_tokens = max_input_tokens.min(MAX_INPUT_TOKENS);
        let mut attempt = Attempt {
            schema_version: "kaze_judge.attempt.v1".into(),
            request,
            provider_calls_started: 0,
            outcome: Outcome::NotSelected,
        };
        let mut stages = Vec::new();
        if attempt.request.reason.is_none() {
            return Ok((attempt, stages));
        }
        let encoded = serde_json::to_vec(&attempt.request).map_err(|_| Failure::InvalidRequest)?;
        if encoded.len() > max_input_bytes || max_input_tokens == 0 {
            attempt.outcome = Outcome::Failed(Failure::BudgetExceeded);
            return Ok((attempt, stages));
        }
        attempt.provider_calls_started = 1;
        attempt.outcome = match self.decide(&attempt.request, max_input_tokens, &mut stages) {
            Ok(observation) => {
                match observation.validate_within(&attempt.request, max_input_tokens, 1) {
                    Ok(()) => Outcome::Completed(observation),
                    Err(error) => Outcome::Failed(error),
                }
            }
            Err(error) => Outcome::Failed(error),
        };
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
}
