//! Tokenizer from bytes, checked the same way as the Native loader, against golden prompts/IDs.
use crate::{now_ms, prompt};
use anyhow::{anyhow, ensure, Result};
use kaze_judge::DecisionRequest;
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Job {
    pub tokenizer_sha256: String,
    pub codes: Vec<String>,
    pub token_ids: Vec<u32>,
    pub cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Case {
    pub name: String,
    pub request: DecisionRequest,
    pub prompt: String,
    pub prompt_layout: String,
    pub input_ids: Vec<u32>,
}

fn first_difference<T: PartialEq>(a: &[T], b: &[T]) -> Option<usize> {
    a.iter()
        .zip(b)
        .position(|(x, y)| x != y)
        .or((a.len() != b.len()).then_some(a.len().min(b.len())))
}

/// Tokenizer built from bytes plus the answer vocabulary it implies, as the Native loader derives it.
pub struct Loaded {
    pub tokenizer: tokenizers::Tokenizer,
    pub codes: Vec<String>,
    pub ids: Vec<u32>,
    pub single_token_after_prefix: bool,
}

impl Loaded {
    pub fn encode(&self, text: &str) -> Result<Vec<u32>> {
        Ok(self
            .tokenizer
            .encode(text, false)
            .map_err(|e| anyhow!("{e}"))?
            .get_ids()
            .to_vec())
    }
}

pub fn load(tokenizer_json: &[u8]) -> Result<Loaded> {
    let mut tokenizer =
        tokenizers::Tokenizer::from_bytes(tokenizer_json).map_err(|e| anyhow!("{e}"))?;
    tokenizer.with_padding(None);
    tokenizer
        .with_truncation(None)
        .map_err(|e| anyhow!("{e}"))?;
    let mut loaded = Loaded {
        tokenizer,
        codes: Vec::new(),
        ids: Vec::new(),
        single_token_after_prefix: true,
    };
    let candidates = (b'A'..=b'Z').map(|c| (c as char).to_string()).chain(
        (b'A'..=b'Z')
            .flat_map(|a| (b'A'..=b'Z').map(move |b| format!("{}{}", a as char, b as char))),
    );
    for code in candidates {
        let tokens = loaded.encode(&code)?;
        if tokens.len() == 1 {
            loaded.codes.push(code);
            loaded.ids.push(tokens[0]);
        }
        if loaded.codes.len() == 255 {
            break;
        }
    }
    let prefix = "<|im_start|>user\nChoose an option.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n";
    let prefix_ids = loaded.encode(prefix)?;
    for (code, id) in loaded.codes.iter().zip(&loaded.ids) {
        let mut expected = prefix_ids.clone();
        expected.push(*id);
        loaded.single_token_after_prefix &= loaded.encode(&format!("{prefix}{code}"))? == expected;
    }
    Ok(loaded)
}

pub fn run(tokenizer_json: &[u8], job: &[u8]) -> Result<Value> {
    let job: Job = serde_json::from_slice(job)?;
    let started = now_ms();
    let digest = format!("{:x}", Sha256::digest(tokenizer_json));
    ensure!(
        digest == job.tokenizer_sha256,
        "tokenizer.json hash mismatch"
    );
    let hashed = now_ms();
    let loaded = load(tokenizer_json)?;
    let vocabulary_done = now_ms();
    let Loaded {
        codes,
        ids,
        single_token_after_prefix,
        ..
    } = &loaded;

    let mut cases = Vec::new();
    for case in &job.cases {
        let rendered = prompt::render(&case.request, codes, &case.prompt_layout)?;
        let t = now_ms();
        let tokens = loaded.encode(&rendered)?;
        let encode_ms = now_ms() - t;
        cases.push(json!({
            "name": case.name,
            "prompt_match": rendered == case.prompt,
            "prompt_first_difference": first_difference(rendered.as_bytes(), case.prompt.as_bytes()),
            "ids_match": tokens == case.input_ids,
            "ids_first_difference": first_difference(&tokens, &case.input_ids),
            "tokens": tokens.len(),
            "expected_tokens": case.input_ids.len(),
            "encode_ms": encode_ms,
        }));
    }
    Ok(json!({
        "schema_version": "kaze_judge.wasm_w0_tokenize.v1",
        "tokenizer_bytes": tokenizer_json.len(),
        "codes_match": *codes == job.codes,
        "token_ids_match": *ids == job.token_ids,
        "single_token_after_prefix": single_token_after_prefix,
        "hash_ms": hashed - started,
        // Since W1 this includes deriving the answer vocabulary (separate in W0 results).
        "load_ms": vocabulary_done - hashed,
        "cases": cases,
    }))
}
