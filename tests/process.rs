#![cfg(feature = "process")]
//! `LocalProcessProvider` with a real Python interpreter and the protocol fixture: the launcher,
//! the wire format and how each worker result maps to a failure. The deadline, kill and
//! reaping contract is tested deterministically in process_launch.rs, because a real
//! interpreter's start-up time is outside the provider's control: on Windows CI runners
//! starting Python has taken more than 10 s (issue #26).
use pure_jeff::*;
use std::{
    path::PathBuf,
    sync::{Mutex, MutexGuard},
    time::{Duration, Instant},
};

/// Deadline of the protocol tests. They do not test the deadline, so it only has to exceed
/// any interpreter start-up; a protocol failure still fails at once.
const PROTOCOL_DEADLINE: Duration = Duration::from_secs(120);
/// Upper bound for returning after the deadline in the timeout test: catches a hang, not slow
/// killing or reaping of a child that is still starting.
const HANG_LIMIT: Duration = Duration::from_secs(60);

/// The tests start one interpreter at a time: concurrent cold starts are what stalled together
/// on CI.
fn one_at_a_time() -> MutexGuard<'static, ()> {
    static LOCK: Mutex<()> = Mutex::new(());
    LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

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
        deadline: Instant::now() + PROTOCOL_DEADLINE,
    }
}
#[test]
fn process_round_trip() {
    let Some((mut provider, _dir)) = setup() else {
        return;
    };
    let _one = one_at_a_time();
    let a = evaluate(&mut provider, request("節約する"), limits()).unwrap();
    assert!(matches!(a.outcome, Outcome::Completed(_)));
    assert_eq!(a.provider_calls_started, 1);
}
#[test]
fn process_failures_are_preserved() {
    let Some((mut provider, _dir)) = setup() else {
        return;
    };
    let _one = one_at_a_time();
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
    let _one = one_at_a_time();
    // The fixture sleeps 8 s after it starts, far past this deadline. Whether the interpreter
    // reaches the fixture before the deadline depends on its start-up time, so both cases are
    // accepted; in both, the child must not outlive the call.
    let mut l = limits();
    l.deadline = Instant::now() + Duration::from_secs(5);
    let outcome = evaluate(&mut provider, request("timeout"), l)
        .unwrap()
        .outcome;
    let returned = Instant::now();
    assert_eq!(outcome, Outcome::Failed(Failure::Timeout));
    assert!(returned >= l.deadline, "returned before the deadline");
    let late = returned - l.deadline;
    assert!(late < HANG_LIMIT, "returned {late:?} after the deadline");
    let started = dir.path().join("manifest.json.started");
    let survived = dir.path().join("manifest.json.survived");
    match std::fs::metadata(&started).and_then(|m| m.modified()) {
        Ok(at) => {
            // A surviving child would write `.survived` 8 s after `.started`.
            let due = at + Duration::from_secs(10);
            if let Ok(wait) = due.duration_since(std::time::SystemTime::now()) {
                std::thread::sleep(wait);
            }
            assert!(!survived.exists(), "the child outlived its deadline");
        }
        Err(_) => {
            // Killed while the interpreter was still starting: the provider reaped it before
            // returning, so the fixture can never run.
            eprintln!(
                "the interpreter did not reach the fixture before the deadline ({late:?} late)"
            );
            std::thread::sleep(Duration::from_secs(1));
            assert!(
                !started.exists() && !survived.exists(),
                "the child outlived its deadline"
            );
        }
    }
}
