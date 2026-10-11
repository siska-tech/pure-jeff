//! Candidate decision evidence, never calibrated recognition risk.
use serde::{Deserialize, Serialize};
use std::{collections::HashSet, time::Instant};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    Ocr,
    Asr,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RoutingReason {
    CandidateCompetition,
    WeakTextSignal,
    EvidenceConflict,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Candidate {
    pub id: String,
    pub text: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionRequest {
    pub request_id: String,
    pub document_id: String,
    pub segment_id: String,
    pub original_text: String,
    pub source: Source,
    pub profile_id: String,
    pub domain: Option<String>,
    /// Fixed, versioned question/prompt definition owned by the backend.
    pub question_id: String,
    /// Order is significant and must be retained in the observation.
    pub candidates: Vec<Candidate>,
    pub reason: Option<RoutingReason>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Artifact {
    pub component: String,
    pub sha256: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateScore {
    pub candidate_id: String,
    /// Distribution over supplied choices; NOT a probability of correct recognition.
    pub option_probability: f64,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Judgment {
    Selected { candidate_id: String },
    Abstained,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub scores: Vec<CandidateScore>,
    pub judgment: Judgment,
    pub temperature: f64,
    pub input_tokens: usize,
    pub forwards: usize,
    /// Backend must identify all relevant checkpoint, tokenizer, readout,
    /// prompt, adapter (when used), quantization and scoring artifacts.
    pub artifacts: Vec<Artifact>,
}
#[derive(Debug, Clone, Copy)]
pub struct Limits {
    pub max_input_bytes: usize,
    pub max_input_tokens: usize,
    pub max_forwards: usize,
    pub deadline: Instant,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Failure {
    InvalidRequest,
    InvalidOutput,
    BudgetExceeded,
    Timeout,
    Unavailable,
}
impl std::fmt::Display for Failure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Failure {}
/// Implementations must preflight token cost and check deadline before each forward.
/// This synchronous API cannot interrupt a native inference call.
pub trait DecisionProvider {
    fn decide(&mut self, request: &DecisionRequest, limits: Limits)
        -> Result<Observation, Failure>;
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
pub enum Outcome {
    NotSelected,
    Completed(Observation),
    Failed(Failure),
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Attempt {
    pub schema_version: String,
    pub request: DecisionRequest,
    pub provider_calls_started: usize,
    pub outcome: Outcome,
}
impl DecisionRequest {
    pub fn validate(&self) -> Result<(), Failure> {
        let identities = [
            &self.request_id,
            &self.document_id,
            &self.segment_id,
            &self.profile_id,
            &self.question_id,
        ];
        let mut ids = HashSet::new();
        if identities.iter().any(|s| s.trim().is_empty())
            || self.original_text.trim().is_empty()
            || self.domain.as_ref().is_some_and(|s| s.trim().is_empty())
            || self.candidates.len() < 2
            || self
                .candidates
                .iter()
                .any(|c| c.id.trim().is_empty() || c.text.trim().is_empty() || !ids.insert(&c.id))
        {
            return Err(Failure::InvalidRequest);
        }
        Ok(())
    }
}
impl Observation {
    pub fn validate(&self, request: &DecisionRequest, limits: Limits) -> Result<(), Failure> {
        self.validate_within(request, limits.max_input_tokens, limits.max_forwards)
    }
    /// The same checks as `validate` without a deadline, for hosts without `Instant`
    /// (browser Wasm). The caller is responsible for its own time limit.
    pub fn validate_within(
        &self,
        request: &DecisionRequest,
        max_input_tokens: usize,
        max_forwards: usize,
    ) -> Result<(), Failure> {
        request.validate()?;
        let mut components = HashSet::new();
        if self.scores.len() != request.candidates.len()
            || self.scores.iter().zip(&request.candidates).any(|(s, c)| {
                s.candidate_id != c.id
                    || !s.option_probability.is_finite()
                    || !(0.0..=1.0).contains(&s.option_probability)
            })
            || (self
                .scores
                .iter()
                .map(|s| s.option_probability)
                .sum::<f64>()
                - 1.0)
                .abs()
                > 1e-6
            || !self.temperature.is_finite()
            || self.temperature <= 0.0
            || self.input_tokens == 0
            || self.forwards == 0
            || self.artifacts.is_empty()
            || self.artifacts.iter().any(|a| {
                a.component.trim().is_empty()
                    || !components.insert(&a.component)
                    || a.sha256.len() != 64
                    || !a.sha256.bytes().all(|b| b.is_ascii_hexdigit())
            })
        {
            return Err(Failure::InvalidOutput);
        }
        if let Judgment::Selected { candidate_id } = &self.judgment {
            let selected = self
                .scores
                .iter()
                .find(|s| &s.candidate_id == candidate_id)
                .ok_or(Failure::InvalidOutput)?;
            if self
                .scores
                .iter()
                .any(|s| s.option_probability > selected.option_probability)
            {
                return Err(Failure::InvalidOutput);
            }
        }
        if self.input_tokens > max_input_tokens || self.forwards > max_forwards {
            return Err(Failure::BudgetExceeded);
        }
        Ok(())
    }
}
/// Explicit opt-in only. Failure never becomes a successful judgment.
/// Panics propagate: the host must discard a panicking provider.
pub fn evaluate(
    provider: &mut impl DecisionProvider,
    request: DecisionRequest,
    limits: Limits,
) -> Result<Attempt, Failure> {
    request.validate()?;
    let mut attempt = Attempt {
        schema_version: "kaze_judge.attempt.v1".into(),
        request,
        provider_calls_started: 0,
        outcome: Outcome::NotSelected,
    };
    if attempt.request.reason.is_none() {
        return Ok(attempt);
    }
    let encoded = serde_json::to_vec(&attempt.request).map_err(|_| Failure::InvalidRequest)?;
    if encoded.len() > limits.max_input_bytes
        || limits.max_input_tokens == 0
        || limits.max_forwards == 0
    {
        attempt.outcome = Outcome::Failed(Failure::BudgetExceeded);
    } else if Instant::now() >= limits.deadline {
        attempt.outcome = Outcome::Failed(Failure::Timeout);
    } else {
        attempt.provider_calls_started = 1;
        let result = provider.decide(&attempt.request, limits);
        attempt.outcome = if Instant::now() >= limits.deadline {
            Outcome::Failed(Failure::Timeout)
        } else {
            match result {
                Ok(observation) => match observation.validate(&attempt.request, limits) {
                    Ok(()) => Outcome::Completed(observation),
                    Err(error) => Outcome::Failed(error),
                },
                Err(error) => Outcome::Failed(error),
            }
        };
    }
    Ok(attempt)
}

#[cfg(feature = "process")]
mod process;
#[cfg(feature = "process")]
pub use process::{LocalProcessProvider, NativeProcessProvider};
