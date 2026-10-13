#![cfg(feature = "process")]
use pure_jeff::*;
use std::{
    path::PathBuf,
    process::Command,
    sync::OnceLock,
    time::{Duration, Instant},
};
fn executable() -> &'static PathBuf {
    static FIXTURE: OnceLock<(tempfile::TempDir, PathBuf)> = OnceLock::new();
    &FIXTURE
        .get_or_init(|| {
            let dir = tempfile::tempdir().unwrap();
            let binary = dir
                .path()
                .join(format!("native-worker{}", std::env::consts::EXE_SUFFIX));
            let source =
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/native_worker.rs");
            let status = Command::new("rustc")
                .arg(source)
                .args(["--edition=2021", "-O", "-o"])
                .arg(&binary)
                .status()
                .unwrap();
            assert!(status.success());
            (dir, binary)
        })
        .1
}
fn setup() -> (NativeProcessProvider, tempfile::TempDir) {
    let dir = tempfile::tempdir().unwrap();
    let manifest = dir.path().join("manifest.json");
    std::fs::write(&manifest, "{}").unwrap();
    (
        NativeProcessProvider::new(executable(), manifest).unwrap(),
        dir,
    )
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
fn native_round_trip_and_protocol_failures() {
    let (mut provider, _dir) = setup();
    let attempt = evaluate(&mut provider, request("normal"), limits()).unwrap();
    assert!(matches!(attempt.outcome, Outcome::Completed(_)));
    assert_eq!(attempt.provider_calls_started, 1);
    for (mode, failure) in [
        ("wrong_id", Failure::InvalidOutput),
        ("wrong_schema", Failure::InvalidOutput),
        ("duplicate_key", Failure::InvalidOutput),
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
            Outcome::Failed(failure),
            "{mode}"
        );
    }
}
#[test]
fn native_preflight_never_starts_worker() {
    let (mut provider, dir) = setup();
    let mut r = request("timeout");
    r.reason = None;
    let attempt = evaluate(&mut provider, r.clone(), limits()).unwrap();
    assert_eq!(attempt.outcome, Outcome::NotSelected);
    assert_eq!(attempt.provider_calls_started, 0);
    assert_eq!(provider.decide(&r, limits()), Err(Failure::InvalidRequest));
    for l in [
        Limits {
            max_input_bytes: 1,
            ..limits()
        },
        Limits {
            max_input_tokens: 0,
            ..limits()
        },
        Limits {
            max_forwards: 0,
            ..limits()
        },
    ] {
        assert_eq!(
            provider.decide(&request("timeout"), l),
            Err(Failure::BudgetExceeded)
        );
    }
    assert_eq!(
        provider.decide(
            &request("timeout"),
            Limits {
                deadline: Instant::now(),
                ..limits()
            }
        ),
        Err(Failure::Timeout)
    );
    assert!(!dir.path().join("manifest.json.started").exists());
}
#[test]
fn native_timeout_kills_and_waits_even_after_response_written() {
    for mode in ["timeout", "late_exit"] {
        let (mut provider, dir) = setup();
        let started = Instant::now();
        let result = evaluate(
            &mut provider,
            request(mode),
            Limits {
                deadline: started + Duration::from_secs(1),
                ..limits()
            },
        )
        .unwrap();
        assert_eq!(result.outcome, Outcome::Failed(Failure::Timeout));
        // Whether the child was killed is checked below: it writes `.survived` 2 seconds after it
        // starts, so a provider that waited for it to exit would leave that file. The time bound
        // only catches a hang; killing and reaping took over 3 seconds on a loaded CI runner.
        assert!(started.elapsed() < Duration::from_secs(10));
        assert!(dir.path().join("manifest.json.started").exists());
        std::thread::sleep(Duration::from_millis(1300));
        assert!(!dir.path().join("manifest.json.survived").exists());
    }
}
