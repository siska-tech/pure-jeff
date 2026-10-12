#![cfg(feature = "process")]
use pure_jeff::*;
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
/// None (test skipped with a message) unless PURE_JEFF_PYTHON names a Python 3.12+ executable.
fn setup() -> Option<(LocalProcessProvider, tempfile::TempDir)> {
    let Some(python) = std::env::var_os("PURE_JEFF_PYTHON").map(PathBuf::from) else {
        eprintln!("skipped: set PURE_JEFF_PYTHON to an absolute Python 3.12+ executable");
        return None;
    };
    let dir = tempfile::tempdir().unwrap();
    let manifest = dir.path().join("manifest.json");
    std::fs::write(&manifest, "{}").unwrap();
    Some((
        LocalProcessProvider::new(
            python,
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/process_worker.py"),
            manifest,
        )
        .unwrap(),
        dir,
    ))
}
fn request(mode: &str) -> DecisionRequest {
    DecisionRequest {
        request_id: "request".into(),
        document_id: "doc".into(),
        segment_id: "seg".into(),
        original_text: mode.into(),
        source: Source::Ocr,
        profile_id: "test".into(),
        domain: None,
        question_id: "transcription-candidate.v1".into(),
        reason: Some(RoutingReason::CandidateCompetition),
        candidates: vec![
            Candidate {
                id: "first".into(),
                text: "節約する".into(),
            },
            Candidate {
                id: "second".into(),
                text: "節税する".into(),
            },
        ],
    }
}
fn limits() -> Limits {
    Limits {
        max_input_bytes: 8192,
        max_input_tokens: 100,
        max_forwards: 1,
        deadline: Instant::now() + Duration::from_secs(10),
    }
}
#[test]
fn process_round_trip() {
    let Some((mut provider, _dir)) = setup() else {
        return;
    };
    let a = evaluate(&mut provider, request("節約する"), limits()).unwrap();
    assert!(matches!(a.outcome, Outcome::Completed(_)));
    assert_eq!(a.provider_calls_started, 1);
}
#[test]
fn process_failures_are_preserved() {
    let Some((mut provider, _dir)) = setup() else {
        return;
    };
    for (mode, expected) in [
        ("wrong_id", Failure::InvalidOutput),
        ("invalid_json", Failure::InvalidOutput),
        ("oversized", Failure::InvalidOutput),
        ("crash", Failure::Unavailable),
        ("unavailable", Failure::Unavailable),
        ("budget", Failure::BudgetExceeded),
    ] {
        assert_eq!(
            evaluate(&mut provider, request(mode), limits())
                .unwrap()
                .outcome,
            Outcome::Failed(expected),
            "{mode}"
        );
    }
}
#[test]
fn direct_provider_also_enforces_preflight() {
    let Some((mut provider, dir)) = setup() else {
        return;
    };
    let mut l = limits();
    l.max_input_bytes = 1;
    assert_eq!(
        provider.decide(&request("timeout"), l),
        Err(Failure::BudgetExceeded)
    );
    let mut r = request("timeout");
    r.reason = None;
    assert_eq!(provider.decide(&r, limits()), Err(Failure::InvalidRequest));
    assert!(!dir.path().join("manifest.json.started").exists());
}
#[test]
fn timeout_terminates_running_child() {
    let Some((mut provider, dir)) = setup() else {
        return;
    };
    // The deadline leaves time for a cold interpreter to start (CI runners can take over a
    // second), while the fixture sleeps far longer than the deadline.
    let mut l = limits();
    l.deadline = Instant::now() + Duration::from_secs(5);
    let start = Instant::now();
    assert_eq!(
        evaluate(&mut provider, request("timeout"), l)
            .unwrap()
            .outcome,
        Outcome::Failed(Failure::Timeout)
    );
    assert!(start.elapsed() < Duration::from_secs(7));
    assert!(
        dir.path().join("manifest.json.started").exists(),
        "fixture must actually start"
    );
    // A surviving child would write this marker about 8 s after it started.
    std::thread::sleep(Duration::from_secs(5));
    assert!(!dir.path().join("manifest.json.survived").exists());
}
