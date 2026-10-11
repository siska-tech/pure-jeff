use crate::{
    bundle::{self, Bundle},
    prompt,
};
use anyhow::{ensure, Result};
use kaze_judge::{DecisionRequest, Failure, Limits};
pub struct Tokenizer(tokenizers::Tokenizer);
pub struct Prepared {
    pub prompt: String,
    pub ids: Vec<u32>,
}
impl Tokenizer {
    pub fn load(bundle: &Bundle) -> Result<Self> {
        let path = bundle.root.join("tokenizer.json");
        let _: serde_json::Value = bundle::read_json(&path, 64 * 1024 * 1024)?;
        let mut tokenizer = tokenizers::Tokenizer::from_bytes(std::fs::read(path)?)
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
            codes == bundle.decision.codes && ids == bundle.decision.token_ids,
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
    pub fn prepare(
        &self,
        bundle: &Bundle,
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
        let prompt = prompt::render(
            request,
            &bundle.decision.codes,
            &bundle.decision.prompt_layout,
        )
        .map_err(|_| Failure::InvalidRequest)?;
        let ids = self
            .0
            .encode(prompt.as_str(), false)
            .map_err(|_| Failure::Unavailable)?
            .get_ids()
            .to_vec();
        if std::time::Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        if ids.is_empty() || ids.len() > limits.max_input_tokens.min(8192) {
            return Err(Failure::BudgetExceeded);
        }
        Ok(Prepared { prompt, ids })
    }
}
