//! The checkpoint's `decision_config.json`: answer vocabulary, temperature and prompt layout.
use anyhow::{ensure, Result};
use serde::Deserialize;
use std::collections::HashSet;

#[derive(Debug, Clone, Deserialize)]
pub struct DecisionConfig {
    pub format_version: u32,
    pub base_model: String,
    pub revision: String,
    pub codes: Vec<String>,
    pub token_ids: Vec<u32>,
    pub temperature: f64,
    #[serde(default = "default_layout")]
    pub prompt_layout: String,
}
fn default_layout() -> String {
    "state-first".into()
}
impl DecisionConfig {
    pub fn validate(&self) -> Result<()> {
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
