//! W1: one decision from in-memory assets, mirroring the Native RustProvider steps
//! (hash checks, decision config, tokenizer, prompt, full forward, readout, policy).
//! No deadline inside the call; the page cancels by terminating the Worker.
use crate::{now_ms, policy::Policy, prompt, slice, tokenize};
use anyhow::{ensure, Context, Result};
use candle_core::safetensors::SliceSafetensors;
use kaze_judge::DecisionRequest;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

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

pub struct Assets<'a> {
    pub manifest: &'a [u8],
    pub decision_config: &'a [u8],
    pub tokenizer: &'a [u8],
    pub readout: &'a [u8],
    pub model: &'a [u8],
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Verified assets and tokenizer, reused across decisions (W2). The asset bytes stay owned
/// by the caller and must not change while the session exists.
pub struct Session<'a> {
    manifest: Manifest,
    config: DecisionConfig,
    tokenizer: tokenize::Loaded,
    readout: &'a [u8],
    model: &'a [u8],
}

impl<'a> Session<'a> {
    /// Checks every asset hash, the decision config and the tokenizer's answer vocabulary.
    pub fn open(assets: &Assets<'a>) -> Result<(Self, Vec<Value>)> {
        let mut stages = Vec::new();
        let mut last = now_ms();
        let mut stage = |name: &str| {
            let now = now_ms();
            stages.push(json!({"name": name, "ms": now - last}));
            last = now;
        };
        let manifest: Manifest = serde_json::from_slice(assets.manifest)?;
        ensure!(
            manifest.schema_version == "pure_jeff.bundle.v1",
            "unsupported manifest"
        );
        manifest.policy.validate()?;
        ensure!(
            candle_core::utils::get_num_threads() == manifest.policy.cpu_threads,
            "compute threads differ from the bundle policy"
        );
        for (path, bytes) in [
            ("decision_config.json", assets.decision_config),
            ("tokenizer.json", assets.tokenizer),
            ("readout.safetensors", assets.readout),
            ("model.safetensors", assets.model),
        ] {
            let record = manifest
                .files
                .iter()
                .find(|f| f.path == path)
                .with_context(|| format!("{path} missing from manifest"))?;
            ensure!(sha256(bytes) == record.sha256, "{path} hash mismatch");
        }
        stage("hash");

        let config: DecisionConfig = serde_json::from_slice(assets.decision_config)?;
        config.validate()?;
        let tokenizer = tokenize::load(assets.tokenizer)?;
        ensure!(
            tokenizer.codes == config.codes
                && tokenizer.ids == config.token_ids
                && tokenizer.single_token_after_prefix,
            "answer vocabulary differs from tokenizer"
        );
        stage("tokenizer");
        let session = Self {
            manifest,
            config,
            tokenizer,
            readout: assets.readout,
            model: assets.model,
        };
        Ok((session, stages))
    }

    pub fn decide(&self, request: &[u8], max_input_tokens: usize) -> Result<Value> {
        let mut stages = Vec::new();
        let mut last = now_ms();
        let mut stage = |name: &str| {
            let now = now_ms();
            stages.push(json!({"name": name, "ms": now - last}));
            last = now;
        };
        let request: DecisionRequest = serde_json::from_slice(request)?;
        request
            .validate()
            .map_err(|f| anyhow::anyhow!("invalid request: {f:?}"))?;
        ensure!(
            request.reason.is_some()
                && request.question_id == prompt::QUESTION_ID
                && request.candidates.len() <= 255,
            "unsupported request"
        );
        let config = &self.config;
        let rendered = prompt::render(&request, &config.codes, &config.prompt_layout)?;
        let ids = self.tokenizer.encode(&rendered)?;
        ensure!(
            !ids.is_empty() && ids.len() <= max_input_tokens.min(8192),
            "token budget exceeded"
        );
        stage("prompt_tokenize");

        let weights = SliceSafetensors::new(self.model)?;
        let hidden = slice::backbone::forward(&weights, &ids)?;
        stage("forward");
        let probabilities = slice::readout::probabilities(
            self.readout,
            &hidden,
            request.candidates.len(),
            config.temperature,
        )?;
        let judgment = self.manifest.policy.judge(&request, &probabilities)?;
        stage("readout_policy");

        Ok(json!({
            "schema_version": "kaze_judge.wasm_w1_decision.v1",
            "rendered_prompt_sha256": sha256(rendered.as_bytes()),
            "input_ids": ids,
            "candidate_ids": request.candidates.iter().map(|c| &c.id).collect::<Vec<_>>(),
            "probabilities": probabilities,
            "judgment": judgment,
            "temperature": config.temperature,
            "last_hidden_state": hidden.flatten_all()?.to_vec1::<f32>()?,
            "compute_threads": candle_core::utils::get_num_threads(),
            "stages": stages,
        }))
    }
}

/// W1 one-shot form: open a session and make one decision; stages include the open.
pub fn decide(assets: &Assets, request: &[u8], max_input_tokens: usize) -> Result<Value> {
    let (session, mut stages) = Session::open(assets)?;
    let mut result = session.decide(request, max_input_tokens)?;
    stages.extend(result["stages"].as_array().cloned().unwrap_or_default());
    result["stages"] = Value::Array(stages);
    Ok(result)
}
