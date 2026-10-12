use crate::{DecisionRequest, Error, ErrorKind, Failure, Judgment};
use serde::{Deserialize, Serialize};
/// Selection policy fixed in the bundle: a candidate is selected only when its probability is at
/// least `min_probability` and leads the runner-up by at least `min_margin` (ties abstain).
/// `cpu_threads` is the compute thread count the decision was validated with.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub min_probability: f64,
    pub min_margin: f64,
    pub cpu_threads: usize,
}
impl Policy {
    /// Thresholds in `[0, 1]` and 1–256 compute threads.
    pub fn validate(&self) -> Result<(), Error> {
        if [self.min_probability, self.min_margin]
            .iter()
            .all(|x| x.is_finite() && (0.0..=1.0).contains(x))
            && (1..=256).contains(&self.cpu_threads)
        {
            Ok(())
        } else {
            Err(Error::new(ErrorKind::InvalidArgument, "invalid policy"))
        }
    }
    /// Applies the policy to a distribution over `request`'s candidates (in request order).
    /// An invalid policy or distribution is `InvalidOutput`.
    pub fn judge(&self, request: &DecisionRequest, p: &[f64]) -> Result<Judgment, Failure> {
        self.validate().map_err(|_| Failure::InvalidOutput)?;
        if !(p.len() == request.candidates.len()
            && p.len() >= 2
            && p.iter().all(|x| x.is_finite() && (0.0..=1.0).contains(x))
            && (p.iter().sum::<f64>() - 1.0).abs() <= 1e-6)
        {
            return Err(Failure::InvalidOutput);
        }
        let mut ranked: Vec<_> = (0..p.len()).collect();
        ranked.sort_by(|a, b| p[*b].total_cmp(&p[*a]));
        let (best, second) = (p[ranked[0]], p[ranked[1]]);
        let margin = best - second;
        Ok(
            if margin > 0.0 && margin >= self.min_margin && best >= self.min_probability {
                Judgment::Selected {
                    candidate_id: request.candidates[ranked[0]].id.clone(),
                }
            } else {
                Judgment::Abstained
            },
        )
    }
}
