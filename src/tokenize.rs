//! Tokenizer of the checkpoint, checked against the decision config's answer vocabulary.
use crate::{config::DecisionConfig, prompt, DecisionRequest, Failure, Limits};
use anyhow::{ensure, Result};
pub struct Tokenizer(tokenizers::Tokenizer);
pub struct Prepared {
    pub prompt: String,
    pub ids: Vec<u32>,
}
impl Tokenizer {
    /// Reads `tokenizer.json` from a verified bundle, rejecting duplicate JSON keys first.
    #[cfg(feature = "native")]
    pub fn load(bundle: &crate::bundle::Bundle) -> Result<Self> {
        let path = bundle.root.join("tokenizer.json");
        let _: serde_json::Value = crate::bundle::read_json(&path, 64 * 1024 * 1024)?;
        Self::from_bytes(&std::fs::read(path)?, &bundle.decision)
    }
    /// Builds the tokenizer and checks that the answer codes it implies (single tokens, also
    /// after the chat prefix) are exactly the config's codes and token IDs.
    pub fn from_bytes(tokenizer_json: &[u8], config: &DecisionConfig) -> Result<Self> {
        let mut tokenizer = tokenizers::Tokenizer::from_bytes(tokenizer_json)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        // One unpadded sequence, with length checked explicitly after encoding.
        // The official tokenizer stores BatchLongest padding for Python batches.
        tokenizer.with_padding(None);
        tokenizer
            .with_truncation(None)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        let encode = |text: &str| -> Result<Vec<u32>> {
            Ok(tokenizer
                .encode(text, false)
                .map_err(|e| anyhow::anyhow!("{e}"))?
                .get_ids()
                .to_vec())
        };
        let mut codes = Vec::new();
        let mut ids = Vec::new();
        let candidates = (b'A'..=b'Z').map(|c| (c as char).to_string()).chain(
            (b'A'..=b'Z')
                .flat_map(|a| (b'A'..=b'Z').map(move |b| format!("{}{}", a as char, b as char))),
        );
        for code in candidates {
            let tokens = encode(&code)?;
            if tokens.len() == 1 {
                codes.push(code);
                ids.push(tokens[0]);
            }
            if codes.len() == 255 {
                break;
            }
        }
        ensure!(
            codes == config.codes && ids == config.token_ids,
            "answer vocabulary differs from tokenizer"
        );
        let prefix="<|im_start|>user\nChoose an option.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";
        let prefix_ids = encode(prefix)?;
        for (code, id) in codes.iter().zip(ids) {
            let mut expected = prefix_ids.clone();
            expected.push(id);
            ensure!(
                encode(&format!("{prefix}{code}"))? == expected,
                "answer code is not one token after chat prefix"
            );
        }
        Ok(Self(tokenizer))
    }
    pub fn encode(&self, text: &str) -> Result<Vec<u32>> {
        Ok(self
            .0
            .encode(text, false)
            .map_err(|e| anyhow::anyhow!("{e}"))?
            .get_ids()
            .to_vec())
    }
    /// Renders and tokenizes one request within its byte, token (at most 8192) and time
    /// limits; never truncates.
    pub fn prepare(
        &self,
        config: &DecisionConfig,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Prepared, Failure> {
        request.validate()?;
        if request.reason.is_none()
            || request.question_id != prompt::QUESTION_ID
            || request.candidates.len() > 255
        {
            return Err(Failure::InvalidRequest);
        }
        let bytes = serde_json::to_vec(request)
            .map_err(|_| Failure::InvalidRequest)?
            .len();
        if bytes > limits.max_input_bytes
            || limits.max_input_tokens == 0
            || limits.max_forwards == 0
        {
            return Err(Failure::BudgetExceeded);
        }
        if std::time::Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        let prompt = prompt::render(request, &config.codes, &config.prompt_layout)
            .map_err(|_| Failure::InvalidRequest)?;
        let ids = self.encode(&prompt).map_err(|_| Failure::Unavailable)?;
        if std::time::Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        if ids.is_empty() || ids.len() > limits.max_input_tokens.min(8192) {
            return Err(Failure::BudgetExceeded);
        }
        Ok(Prepared { prompt, ids })
    }
}
