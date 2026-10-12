//! The decision steps shared by the Native [`Model`](crate::Model) and the in-memory
//! [`Session`](crate::memory::Session): prompt, tokens, forward, readout, policy, artifacts.
use crate::{
    backbone, config::DecisionConfig, manifest::Manifest, prompt, readout, tokenize::Tokenizer,
    Artifact, CandidateScore, DecisionRequest, Failure, Observation, WeightSource,
};
use sha2::{Digest, Sha256};

/// Hard ceiling of the supported checkpoint, whatever the caller's budget.
pub(crate) const MAX_INPUT_TOKENS: usize = 8192;

pub(crate) struct Decider<'a> {
    pub manifest: &'a Manifest,
    pub manifest_sha256: &'a str,
    /// The artifact identifying the executing runtime (Native build or browser engine).
    pub runtime: &'a Artifact,
    pub config: &'a DecisionConfig,
    pub tokenizer: &'a Tokenizer,
    pub weights: &'a dyn WeightSource,
    pub readout: &'a dyn WeightSource,
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

/// Request checks that need no model: validity, the supported question and candidate count.
pub(crate) fn check_request(request: &DecisionRequest) -> Result<(), Failure> {
    request.validate()?;
    if request.reason.is_none()
        || request.question_id != prompt::QUESTION_ID
        || request.candidates.len() > 255
    {
        return Err(Failure::InvalidRequest);
    }
    Ok(())
}

impl Decider<'_> {
    /// One forward for an already checked request. `expired` reports a passed deadline (always
    /// false without a clock); `stage` is called after tokenization, forward and readout.
    pub fn decide(
        &self,
        request: &DecisionRequest,
        max_input_tokens: usize,
        expired: &dyn Fn() -> bool,
        stage: &mut dyn FnMut(&'static str),
    ) -> Result<Observation, Failure> {
        let unavailable = || {
            if expired() {
                Failure::Timeout
            } else {
                Failure::Unavailable
            }
        };
        let timeout = || {
            if expired() {
                Err(Failure::Timeout)
            } else {
                Ok(())
            }
        };
        let rendered = prompt::render(request, &self.config.codes, &self.config.prompt_layout)
            .map_err(|_| Failure::InvalidRequest)?;
        let ids = self
            .tokenizer
            .encode(&rendered)
            .map_err(|_| Failure::Unavailable)?;
        timeout()?;
        if ids.is_empty() || ids.len() > max_input_tokens.min(MAX_INPUT_TOKENS) {
            return Err(Failure::BudgetExceeded);
        }
        stage("prompt_tokenize");
        timeout()?;
        let check = || {
            if expired() {
                candle_core::bail!("deadline exceeded");
            }
            Ok(())
        };
        let hidden =
            backbone::forward_checked(self.weights, &ids, &check).map_err(|_| unavailable())?;
        stage("forward");
        timeout()?;
        let probabilities = readout::probabilities(
            self.readout,
            &hidden,
            request.candidates.len(),
            self.config.temperature,
        )
        .map_err(|_| unavailable())?;
        timeout()?;
        let judgment = self.manifest.policy.judge(request, &probabilities)?;
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
        for (component, sha256) in [
            ("bundle_manifest", self.manifest_sha256.to_owned()),
            (self.runtime.component.as_str(), self.runtime.sha256.clone()),
            ("prompt", self.manifest.prompt_sha256.clone()),
            ("rendered_prompt", sha256(rendered.as_bytes())),
            ("policy", sha256(&policy)),
        ] {
            artifacts.push(Artifact {
                component: component.into(),
                sha256,
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
            temperature: self.config.temperature,
            input_tokens: ids.len(),
            forwards: 1,
            artifacts,
        })
    }
}
