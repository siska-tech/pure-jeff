//! A separate project that uses pure-jeff only through its public API, as a crates.io user
//! would. Built by tools/check_package.py against the packaged crate.
//!
//!   consumer                               model-free checks of the public API
//!   consumer <manifest> <golden-dir>       also decide every official golden request
use pure_jeff::{
    evaluate, Attempt, DecisionProvider, DecisionRequest, ErrorKind, Failure, Judgment, Limits,
    LoadOptions, Model, Observation, Outcome,
};
use std::time::{Duration, Instant};

const GOLDENS: [&str; 7] = [
    "candidate-request",
    "reversed",
    "asr-unicode",
    "long-text",
    "special-token-text",
    "maximum-candidates",
    "token-limit-8192",
];

fn limits() -> Limits {
    Limits {
        max_input_bytes: 1024 * 1024,
        max_input_tokens: 8192,
        max_forwards: 1,
        deadline: Instant::now() + Duration::from_secs(1800),
    }
}

fn request() -> DecisionRequest {
    serde_json::from_value(serde_json::json!({
        "request_id": "r1", "document_id": "d1", "segment_id": "s1",
        "original_text": "teh cat", "source": "ocr", "profile_id": "p1", "domain": null,
        "question_id": "transcription-candidate.v1",
        "candidates": [{"id": "a", "text": "the cat"}, {"id": "b", "text": "teh cat"}],
        "reason": "candidate_competition"
    }))
    .unwrap()
}

struct Never;
impl DecisionProvider for Never {
    fn decide(&mut self, _: &DecisionRequest, _: Limits) -> Result<Observation, Failure> {
        Err(Failure::Unavailable)
    }
}

fn model_free() {
    request().validate().unwrap();
    // A failure is reported as a failed attempt, never as a judgment.
    let attempt: Attempt = evaluate(&mut Never, request(), limits()).unwrap();
    assert_eq!(attempt.schema_version, pure_jeff::ATTEMPT_SCHEMA);
    assert_eq!(attempt.outcome, Outcome::Failed(Failure::Unavailable));
    let error = Model::load("no-such-bundle.json", &LoadOptions::default())
        .err()
        .unwrap();
    assert_eq!(error.kind(), ErrorKind::Bundle);
    assert_eq!(pure_jeff::runtime_build_hash().len(), 64);
    println!("model-free checks passed");
}

fn goldens(manifest: &str, dir: &str) {
    pure_jeff::configure_threads(1).unwrap();
    let model = Model::load(manifest, &LoadOptions::default()).unwrap();
    let mut worst = 0.0_f64;
    for name in GOLDENS {
        let path = std::path::Path::new(dir).join(format!("{name}.json"));
        let golden: serde_json::Value =
            serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        let request: DecisionRequest = serde_json::from_value(golden["request"].clone()).unwrap();
        let observation = model.decide(&request, limits()).unwrap();
        let official: Vec<f64> =
            serde_json::from_value(golden["official"]["probabilities"].clone()).unwrap();
        let judgment: Judgment =
            serde_json::from_value(golden["official"]["judgment"].clone()).unwrap();
        let tokens = golden["official"]["input_tokens"].as_u64().unwrap() as usize;
        let error = observation
            .scores
            .iter()
            .zip(&official)
            .map(|(s, p)| (s.option_probability - p).abs())
            .fold(0.0, f64::max);
        let passed = error <= 1e-4
            && observation.judgment == judgment
            && observation.input_tokens == tokens
            && observation.scores.len() == official.len();
        worst = worst.max(error);
        println!(
            "{}",
            serde_json::json!({"case": name, "max_error": error, "input_tokens": observation.input_tokens,
                "judgment": observation.judgment, "passed": passed})
        );
        assert!(passed, "{name} differs from the official reference");
    }
    println!("all {} goldens passed; worst probability error {worst:e}", GOLDENS.len());
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    model_free();
    if args.len() == 3 {
        goldens(&args[1], &args[2]);
    }
}
