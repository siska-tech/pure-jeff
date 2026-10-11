//! Experimental fixed-0.8B Rust runtime. Native inference is cooperatively stopped.
pub mod backbone;
pub mod bundle;
pub mod json;
pub mod policy;
pub mod prompt;
pub mod readout;
pub mod tokenize;
pub mod worker;

use kaze_judge::{
    Artifact, CandidateScore, DecisionProvider, DecisionRequest, Failure, Limits, Observation,
};
use std::{path::PathBuf, time::Instant};
pub struct RustProvider {
    manifest: PathBuf,
}
impl RustProvider {
    pub fn new(manifest: impl Into<PathBuf>) -> Self {
        Self {
            manifest: manifest.into(),
        }
    }
    fn unavailable(limits: Limits) -> Failure {
        if Instant::now() >= limits.deadline {
            Failure::Timeout
        } else {
            Failure::Unavailable
        }
    }
}
impl DecisionProvider for RustProvider {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        request.validate()?;
        if request.reason.is_none()
            || request.question_id != prompt::QUESTION_ID
            || request.candidates.len() > 255
        {
            return Err(Failure::InvalidRequest);
        }
        if serde_json::to_vec(request)
            .map_err(|_| Failure::InvalidRequest)?
            .len()
            > limits.max_input_bytes
            || limits.max_input_tokens == 0
            || limits.max_forwards == 0
        {
            return Err(Failure::BudgetExceeded);
        }
        if Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        let bundle = bundle::Bundle::verify(&self.manifest, limits.deadline)
            .map_err(|_| Self::unavailable(limits))?;
        // Thread pools are process-wide: callers configure them before using this provider.
        if candle_core::utils::get_num_threads() != bundle.manifest.policy.cpu_threads
            || std::env::var("CANDLE_NUM_THREADS")
                .ok()
                .and_then(|s| s.parse::<usize>().ok())
                != Some(bundle.manifest.policy.cpu_threads)
        {
            return Err(Failure::Unavailable);
        }
        let tokenizer =
            tokenize::Tokenizer::load(&bundle).map_err(|_| Self::unavailable(limits))?;
        let prepared = tokenizer.prepare(&bundle, request, limits)?;
        bundle::check_time(limits.deadline).map_err(|_| Failure::Timeout)?;
        // SAFETY: checked local bundle; caller must prevent mutation until inference finishes.
        let weights = unsafe {
            candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))
        }
        .map_err(|_| Self::unavailable(limits))?;
        let check = || {
            if Instant::now() >= limits.deadline {
                candle_core::bail!("deadline exceeded");
            }
            Ok(())
        };
        check().map_err(|_| Failure::Timeout)?;
        let hidden = backbone::forward_checked(&weights, &prepared.ids, &check)
            .map_err(|_| Self::unavailable(limits))?;
        check().map_err(|_| Failure::Timeout)?;
        let probabilities = readout::probabilities(
            &bundle.root,
            &hidden,
            request.candidates.len(),
            bundle.decision.temperature,
        )
        .map_err(|_| Self::unavailable(limits))?;
        check().map_err(|_| Failure::Timeout)?;
        let judgment = bundle
            .manifest
            .policy
            .judge(request, &probabilities)
            .map_err(|_| Failure::InvalidOutput)?;
        let mut artifacts: Vec<_> = bundle
            .manifest
            .files
            .iter()
            .map(|r| Artifact {
                component: r.path.clone(),
                sha256: r.sha256.clone(),
            })
            .collect();
        for (component, sha256) in [
            ("bundle_manifest", bundle.manifest_sha256),
            ("runtime_build", bundle.manifest.runtime_build_sha256),
            ("prompt", bundle.manifest.prompt_sha256),
            (
                "rendered_prompt",
                bundle::hash_bytes(prepared.prompt.as_bytes()),
            ),
            (
                "policy",
                bundle::hash_bytes(
                    &serde_json::to_vec(&bundle.manifest.policy)
                        .map_err(|_| Failure::Unavailable)?,
                ),
            ),
        ] {
            artifacts.push(Artifact {
                component: component.into(),
                sha256,
            });
        }
        let observation = Observation {
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
            temperature: bundle.decision.temperature,
            input_tokens: prepared.ids.len(),
            forwards: 1,
            artifacts,
        };
        observation.validate(request, limits)?;
        check().map_err(|_| Failure::Timeout)?;
        Ok(observation)
    }
}
