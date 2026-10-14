#![cfg(feature = "process")]
//! The deadline, kill and reaping contract of `LocalProcessProvider`, independent of how long
//! a real Python interpreter takes to start. The interpreter is replaced by a compiled
//! stand-in (tests/fixtures/fake_python.rs) that starts in milliseconds, checks the launcher's
//! command line and environment, and then waits a chosen time before acting, as a slow
//! interpreter would. Real Python is exercised by tests/process.rs.
use pure_jeff::*;
use std::{
    path::{Path, PathBuf},
    process::Command,
    sync::OnceLock,
    time::{Duration, Instant},
};

/// Upper bound for returning after the deadline. Not a performance claim: it only catches a
/// provider that hangs instead of killing and reaping. Killing and reaping has taken over 3 s
/// on loaded CI runners.
const HANG_LIMIT: Duration = Duration::from_secs(20);

fn interpreter() -> &'static PathBuf {
    static FIXTURE: OnceLock<(tempfile::TempDir, PathBuf)> = OnceLock::new();
    &FIXTURE
        .get_or_init(|| {
            let dir = tempfile::tempdir().unwrap();
            let binary = dir
                .path()
                .join(format!("fake-python{}", std::env::consts::EXE_SUFFIX));
            let source =
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fake_python.rs");
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

fn setup() -> (LocalProcessProvider, tempfile::TempDir) {
    let dir = tempfile::tempdir().unwrap();
    let manifest = dir.path().join("manifest.json");
    std::fs::write(&manifest, "{}").unwrap();
    // The stand-in ignores the worker script; any existing file satisfies the provider.
    let worker = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/process_worker.py");
    (
        LocalProcessProvider::new(interpreter(), worker, manifest).unwrap(),
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

fn limits(deadline: Duration) -> Limits {
    Limits {
        max_input_bytes: 8192,
        max_input_tokens: 100,
        max_forwards: 1,
        deadline: Instant::now() + deadline,
    }
}

fn marker(dir: &Path, name: &str) -> bool {
    dir.join(format!("manifest.json.{name}")).exists()
}

/// Runs one decision that must time out; checks that it returned after the deadline and
/// within the hang limit, and returns how long after the deadline it returned.
fn expect_timeout(provider: &mut LocalProcessProvider, mode: &str, deadline: Duration) -> Duration {
    let limits = limits(deadline);
    let outcome = evaluate(provider, request(mode), limits).unwrap().outcome;
    let returned = Instant::now();
    assert_eq!(outcome, Outcome::Failed(Failure::Timeout), "{mode}");
    assert!(
        returned >= limits.deadline,
        "{mode}: returned before the deadline"
    );
    let late = returned - limits.deadline;
    assert!(
        late < HANG_LIMIT,
        "{mode}: returned {late:?} after the deadline"
    );
    late
}

#[test]
fn a_slow_start_within_the_deadline_completes() {
    let (mut provider, dir) = setup();
    let attempt = evaluate(
        &mut provider,
        request("slow_start_ms=1500"),
        limits(Duration::from_secs(30)),
    )
    .unwrap();
    // Completed also proves the launcher passed `-I -B`, the paths and the offline variables.
    assert!(
        matches!(attempt.outcome, Outcome::Completed(_)),
        "{:?}",
        attempt.outcome
    );
    assert!(marker(dir.path(), "started"));
}

#[test]
fn a_start_slower_than_the_deadline_times_out_and_the_child_is_reaped() {
    let (mut provider, dir) = setup();
    let late = expect_timeout(
        &mut provider,
        "slow_start_ms=3000",
        Duration::from_millis(500),
    );
    // The stand-in would write `.started` 3 s after it began; it was killed and reaped before.
    std::thread::sleep(Duration::from_secs(4).saturating_sub(late));
    assert!(
        !marker(dir.path(), "started"),
        "the child outlived its deadline"
    );
}

#[test]
fn a_running_child_past_the_deadline_is_killed_and_reaped() {
    let (mut provider, dir) = setup();
    let late = expect_timeout(&mut provider, "timeout", Duration::from_millis(1500));
    assert!(
        marker(dir.path(), "started"),
        "the stand-in must have started"
    );
    std::thread::sleep(Duration::from_secs(4).saturating_sub(late));
    assert!(
        !marker(dir.path(), "survived"),
        "the child outlived its deadline"
    );
}

#[test]
fn a_response_followed_by_a_late_exit_is_a_timeout_and_the_child_is_killed() {
    let (mut provider, dir) = setup();
    let late = expect_timeout(&mut provider, "late_exit", Duration::from_millis(1500));
    assert!(
        marker(dir.path(), "started"),
        "the stand-in must have started"
    );
    std::thread::sleep(Duration::from_secs(4).saturating_sub(late));
    assert!(
        !marker(dir.path(), "survived"),
        "the child outlived its deadline"
    );
}
