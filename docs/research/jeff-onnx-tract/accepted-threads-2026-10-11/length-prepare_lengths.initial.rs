//! Development fixtures encoded by the unchanged Native prompt and tokenizer.
use anyhow::{ensure, Result};
use kaze_judge::{Candidate, DecisionRequest, Failure, Limits, RoutingReason, Source};
use kaze_judge_jeff::{
    bundle::{self, Bundle},
    tokenize::Tokenizer,
};
use serde_json::{json, Value};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::Path,
    time::{Duration, Instant},
};

fn limits(tokens: usize, deadline: Instant) -> Limits {
    Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: tokens,
        max_forwards: 1,
        deadline,
    }
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    ensure!(
        args.len() == 2,
        "usage: prepare_lengths manifest new-output.json"
    );
    ensure!(!Path::new(&args[1]).exists(), "new output required");
    let deadline = Instant::now() + Duration::from_secs(600);
    let bundle = Bundle::verify(Path::new(&args[0]), deadline)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    let mut golden_checks = Vec::new();
    for id in [
        "candidate-request",
        "reversed",
        "asr-unicode",
        "special-token-text",
    ] {
        let path = format!("tests/fixtures/jeff-golden/{id}.json");
        let golden: Value = serde_json::from_slice(&fs::read(&path)?)?;
        let request: DecisionRequest = serde_json::from_value(golden["request"].clone())?;
        let prepared = tokenizer.prepare(&bundle, &request, limits(512, deadline))?;
        ensure!(
            prepared.prompt == golden["prompt"].as_str().unwrap(),
            "golden prompt mismatch"
        );
        ensure!(
            json!([prepared.ids]) == golden["official"]["inputs"]["input_ids"],
            "golden IDs mismatch"
        );
        golden_checks.push(json!({"id":id,"sha256":bundle::hash_file(Path::new(&path),deadline)?}));
    }
    let variants = [
        (
            "ocr-ja-2",
            Source::Ocr,
            "猫です。",
            vec!["猫です。", "犬です。"],
        ),
        (
            "asr-unicode-2",
            Source::Asr,
            "café🙂",
            vec!["café🙂", "cafe"],
        ),
        ("ocr-ascii-3", Source::Ocr, "cat", vec!["cat", "car", "cap"]),
        ("asr-mixed-3", Source::Asr, "駅A", vec!["駅A", "駅B", "駅C"]),
        (
            "ocr-ascii-8",
            Source::Ocr,
            "cat",
            vec!["a", "b", "c", "d", "e", "f", "g", "h"],
        ),
    ];
    let mut cases = Vec::new();
    let mut boundary = Value::Null;
    for (variant, source, seed, texts) in variants {
        let targets = if texts.len() == 8 {
            vec![256, 384, 511, 512]
        } else {
            vec![128, 256, 384, 511, 512]
        };
        for target in targets {
            let mut request = DecisionRequest {
                request_id: format!("synthetic-{variant}-{target}"),
                document_id: "length-pilot".into(),
                segment_id: variant.into(),
                original_text: seed.into(),
                source: source.clone(),
                profile_id: "synthetic.length-pilot".into(),
                domain: None,
                question_id: "transcription-candidate.v1".into(),
                candidates: texts
                    .iter()
                    .enumerate()
                    .map(|(i, text)| Candidate {
                        id: ((b'a' + i as u8) as char).to_string(),
                        text: (*text).into(),
                    })
                    .collect(),
                reason: Some(RoutingReason::CandidateCompetition),
            };
            let mut found = None;
            for repeats in 0..=600 {
                request.original_text = format!("{seed}{}", " a".repeat(repeats));
                let prepared = tokenizer.prepare(&bundle, &request, limits(8192, deadline))?;
                if prepared.ids.len() == target {
                    found = Some((repeats, prepared));
                    break;
                }
            }
            let (repeats, prepared) =
                found.ok_or_else(|| anyhow::anyhow!("unreachable target {variant}/{target}"))?;
            tokenizer.prepare(&bundle, &request, limits(target, deadline))?;
            ensure!(
                matches!(
                    tokenizer.prepare(&bundle, &request, limits(target - 1, deadline)),
                    Err(Failure::BudgetExceeded)
                ),
                "one-short budget accepted"
            );
            let mut ids = vec![248044_u32; 512 - target];
            ids.extend_from_slice(&prepared.ids);
            let mut mask = vec![0_u32; 512 - target];
            mask.extend(vec![1_u32; target]);
            let request_bytes = serde_json::to_vec(&request)?;
            cases.push(json!({"id":request.request_id,"variant":variant,"request":request,
                "request_utf8_sha256":bundle::hash_bytes(&request_bytes),
                "prompt":prepared.prompt,"prompt_utf8_sha256":bundle::hash_bytes(prepared.prompt.as_bytes()),
                "token_ids_sha256":bundle::hash_bytes(&serde_json::to_vec(&prepared.ids)?),
                "tokens":target,"physical_tokens":512,"candidate_count":texts.len(),"filler_repeats":repeats,
                "temperature":bundle.decision.temperature,"inputs":{"input_ids":ids,"attention_mask":mask,"mm_token_type_ids":vec![0_u32;512]},
                "exact_budget_accepted":true,"one_short_budget_rejected":true}));
            if variant == "ocr-ascii-3" && target == 512 {
                let mut rejected = request.clone();
                rejected.original_text.push_str(" a");
                let overflow = tokenizer.prepare(&bundle, &rejected, limits(8192, deadline))?;
                ensure!(overflow.ids.len() == 513, "boundary is not 513");
                ensure!(
                    matches!(
                        tokenizer.prepare(&bundle, &rejected, limits(512, deadline)),
                        Err(Failure::BudgetExceeded)
                    ),
                    "513 accepted"
                );
                boundary = json!({"request":rejected,"tokens":513,"limit":512,"failure":"budget_exceeded"});
            }
        }
    }
    ensure!(
        cases.len() == 24 && !boundary.is_null(),
        "fixture coverage mismatch"
    );
    let output = json!({"schema_version":"kaze_judge.synthetic_length_inputs.v1","manifest_sha256":bundle::hash_file(Path::new(&args[0]),deadline)?,
        "golden_checks":golden_checks,"cases":cases,"boundary_513":boundary,
        "oracle_validated":false,"quality_labels":false,
        "scope":"Full Rust-rendered requests, artificial state suffix, physical512. Four variants per length; extra 8-candidate cases at 256/384/511/512. Candidate text stays fixed while source state grows. Content/length are confounded; no OCR/ASR quality ground truth."});
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[1])?;
    serde_json::to_writer_pretty(&mut file, &output)?;
    writeln!(file)?;
    println!("24 length fixtures, golden prompt/IDs exact, exact/one-short budgets and 513 rejection; oracle pending");
    Ok(())
}
