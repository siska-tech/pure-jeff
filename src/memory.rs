//! Decisions from checkpoint bytes held in memory, without files or a clock (browser Wasm).
//!
//! The same checks and steps as [`Model`](crate::Model), except that the caller owns the time
//! limit (for example by terminating a Web Worker) and the bundle manifest's prompt and build
//! fields are not compared with this library.
use crate::{
    config::DecisionConfig,
    decide::{check_request, Decider},
    manifest::{Manifest, SCHEMA},
    tokenize::Tokenizer,
    Artifact, Attempt, DecisionRequest, Error, ErrorKind, Failure, Observation, Outcome,
    ATTEMPT_SCHEMA,
};
use candle_core::safetensors::SliceSafetensors;
use sha2::{Digest, Sha256};

/// The checkpoint files a session needs, in this order.
pub const ASSET_FILES: [&str; 4] = [
    "decision_config.json",
    "tokenizer.json",
    "readout.safetensors",
    "model.safetensors",
];

/// Bundle manifest and checkpoint bytes. They must stay allocated and unchanged while a
/// [`Session`] borrows them.
pub struct Assets<'a> {
    pub manifest: &'a [u8],
    /// In [`ASSET_FILES`] order.
    pub files: [&'a [u8]; 4],
}

/// Verified assets and tokenizer, reused across decisions.
pub struct Session<'a> {
    manifest: Manifest,
    manifest_sha256: String,
    runtime: Artifact,
    config: DecisionConfig,
    tokenizer: Tokenizer,
    readout: &'a [u8],
    model: &'a [u8],
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn bundle(message: impl std::fmt::Display) -> Error {
    Error::new(ErrorKind::Bundle, message)
}

impl<'a> Session<'a> {
    /// Verifies the manifest and every asset (see [`Session::open_with`]). `runtime` identifies
    /// the executing code in each observation, for example
    /// `("runtime_build", pure_jeff::runtime_build_hash())`.
    pub fn open(assets: &Assets<'a>, runtime: Artifact) -> Result<Self, Error> {
        Self::open_with(assets, [None, None, None, None], runtime, &mut |_| {}).map(|(s, _)| s)
    }

    /// Checks the manifest schema and policy, that the compute threads equal the policy, every
    /// asset's SHA-256 against the manifest, the decision config and the tokenizer's answer
    /// vocabulary. A `digests` entry is the already computed SHA-256 of that asset (for example
    /// while it streamed in); missing ones are computed here and listed in the result. `stage`
    /// is called with `"hash"` and `"tokenizer"` as those steps finish.
    pub fn open_with(
        assets: &Assets<'a>,
        digests: [Option<String>; 4],
        runtime: Artifact,
        stage: &mut dyn FnMut(&'static str),
    ) -> Result<(Self, Vec<&'static str>), Error> {
        let manifest_sha256 = sha256(assets.manifest);
        let manifest: Manifest = serde_json::from_slice(assets.manifest).map_err(bundle)?;
        if manifest.schema_version != SCHEMA {
            return Err(bundle("unsupported manifest"));
        }
        manifest.policy.validate()?;
        if candle_core::utils::get_num_threads() != manifest.policy.cpu_threads {
            return Err(Error::new(
                ErrorKind::ThreadConfig,
                "compute threads differ from the bundle policy",
            ));
        }
        let mut hashed_now = Vec::new();
        for ((path, bytes), digest) in ASSET_FILES.iter().zip(assets.files).zip(digests) {
            let record = manifest
                .files
                .iter()
                .find(|f| f.path == *path)
                .ok_or_else(|| bundle(format!("{path} missing from manifest")))?;
            let digest = match digest {
                Some(digest) => digest,
                None => {
                    hashed_now.push(*path);
                    sha256(bytes)
                }
            };
            if digest != record.sha256 {
                return Err(bundle(format!("{path} hash mismatch")));
            }
        }
        stage("hash");
        let config: DecisionConfig = serde_json::from_slice(assets.files[0]).map_err(bundle)?;
        config.validate().map_err(bundle)?;
        let tokenizer = Tokenizer::from_bytes(assets.files[1], &config)
            .map_err(|e| bundle(format!("{e:#}")))?;
        stage("tokenizer");
        let session = Self {
            manifest,
            manifest_sha256,
            runtime,
            config,
            tokenizer,
            readout: assets.files[2],
            model: assets.files[3],
        };
        Ok((session, hashed_now))
    }

    pub fn manifest(&self) -> &Manifest {
        &self.manifest
    }

    /// One decision within `max_input_tokens` (at most 8192), without a deadline.
    pub fn decide(
        &self,
        request: &DecisionRequest,
        max_input_tokens: usize,
    ) -> Result<Observation, Failure> {
        self.decide_with(request, max_input_tokens, &mut |_| {})
    }

    /// As [`Session::decide`]; `stage` is called with `"prompt_tokenize"`, `"forward"` and
    /// `"readout_policy"` as those steps finish.
    pub fn decide_with(
        &self,
        request: &DecisionRequest,
        max_input_tokens: usize,
        stage: &mut dyn FnMut(&'static str),
    ) -> Result<Observation, Failure> {
        check_request(request)?;
        let weights = SliceSafetensors::new(self.model).map_err(|_| Failure::Unavailable)?;
        let readout = SliceSafetensors::new(self.readout).map_err(|_| Failure::Unavailable)?;
        Decider {
            manifest: &self.manifest,
            manifest_sha256: &self.manifest_sha256,
            runtime: &self.runtime,
            config: &self.config,
            tokenizer: &self.tokenizer,
            weights: &weights,
            readout: &readout,
            // Not validated in the browser yet (linear memory only grows); see issue #14.
            reuse_buffers: false,
        }
        .decide(request, max_input_tokens, &|| false, stage)
    }

    /// [`evaluate`](crate::evaluate) without a clock: an invalid request is an error, no routing
    /// reason means no decision, a request over `max_input_bytes` or a zero token budget fails
    /// with `BudgetExceeded`, and a failure is never turned into a judgment.
    pub fn evaluate(
        &self,
        request: DecisionRequest,
        max_input_bytes: usize,
        max_input_tokens: usize,
        stage: &mut dyn FnMut(&'static str),
    ) -> Result<Attempt, Failure> {
        request.validate()?;
        let mut attempt = Attempt {
            schema_version: ATTEMPT_SCHEMA.into(),
            request,
            provider_calls_started: 0,
            outcome: Outcome::NotSelected,
        };
        if attempt.request.reason.is_none() {
            return Ok(attempt);
        }
        let encoded = serde_json::to_vec(&attempt.request).map_err(|_| Failure::InvalidRequest)?;
        if encoded.len() > max_input_bytes || max_input_tokens == 0 {
            attempt.outcome = Outcome::Failed(Failure::BudgetExceeded);
            return Ok(attempt);
        }
        attempt.provider_calls_started = 1;
        attempt.outcome = match self.decide_with(&attempt.request, max_input_tokens, stage) {
            Ok(observation) => {
                match observation.validate_within(&attempt.request, max_input_tokens, 1) {
                    Ok(()) => Outcome::Completed(observation),
                    Err(error) => Outcome::Failed(error),
                }
            }
            Err(error) => Outcome::Failed(error),
        };
        Ok(attempt)
    }
}
