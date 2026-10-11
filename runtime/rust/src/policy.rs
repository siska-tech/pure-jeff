use anyhow::{ensure, Result};
use kaze_judge::{DecisionRequest, Judgment};
use serde::{Deserialize, Serialize};
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub min_probability: f64,
    pub min_margin: f64,
    pub cpu_threads: usize,
}
impl Policy {
    pub fn validate(&self) -> Result<()> {
        ensure!(
            [self.min_probability, self.min_margin]
                .iter()
                .all(|x| x.is_finite() && (0.0..=1.0).contains(x))
                && (1..=256).contains(&self.cpu_threads),
            "invalid policy"
        );
        Ok(())
    }
    pub fn judge(&self, request: &DecisionRequest, p: &[f64]) -> Result<Judgment> {
        self.validate()?;
        ensure!(
            p.len() == request.candidates.len()
                && p.len() >= 2
                && p.iter().all(|x| x.is_finite() && (0.0..=1.0).contains(x))
                && (p.iter().sum::<f64>() - 1.0).abs() <= 1e-6,
            "invalid probability distribution"
        );
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
