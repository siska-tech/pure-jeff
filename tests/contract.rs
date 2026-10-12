use pure_jeff::*;
use std::time::{Duration, Instant};
fn request() -> DecisionRequest {
    DecisionRequest {
        request_id: "req-1".into(),
        document_id: "doc-1".into(),
        segment_id: "line-1".into(),
        original_text: "節約する".into(),
        source: Source::Ocr,
        profile_id: "ja.ocr.v1".into(),
        domain: None,
        question_id: "transcription-candidate.v1".into(),
        reason: Some(RoutingReason::CandidateCompetition),
        candidates: vec![
            Candidate {
                id: "original".into(),
                text: "節約する".into(),
            },
            Candidate {
                id: "alternative".into(),
                text: "節税する".into(),
            },
        ],
    }
}
fn limits() -> Limits {
    Limits {
        max_input_bytes: 8192,
        max_input_tokens: 128,
        max_forwards: 1,
        deadline: Instant::now() + Duration::from_secs(5),
    }
}
fn observation() -> Observation {
    Observation {
        scores: vec![
            CandidateScore {
                candidate_id: "original".into(),
                option_probability: 0.75,
            },
            CandidateScore {
                candidate_id: "alternative".into(),
                option_probability: 0.25,
            },
        ],
        judgment: Judgment::Selected {
            candidate_id: "original".into(),
        },
        temperature: 1.0,
        input_tokens: 20,
        forwards: 1,
        artifacts: vec![Artifact {
            component: "test_fixture_only".into(),
            sha256: "a".repeat(64),
        }],
    }
}
struct Fixture {
    calls: usize,
    result: Result<Observation, Failure>,
}
impl DecisionProvider for Fixture {
    fn decide(&mut self, _: &DecisionRequest, _: Limits) -> Result<Observation, Failure> {
        self.calls += 1;
        self.result.clone()
    }
}
fn fixture() -> Fixture {
    Fixture {
        calls: 0,
        result: Ok(observation()),
    }
}
#[test]
fn preserves_input_and_round_trips() {
    let req = request();
    let attempt = evaluate(&mut fixture(), req.clone(), limits()).unwrap();
    assert_eq!(attempt.request, req);
    assert!(matches!(attempt.outcome, Outcome::Completed(_)));
    assert_eq!(
        serde_json::from_str::<Attempt>(&serde_json::to_string(&attempt).unwrap()).unwrap(),
        attempt
    );
}
#[test]
fn opt_in_and_preflight_do_not_call_provider() {
    let mut p = fixture();
    let mut r = request();
    r.reason = None;
    assert_eq!(
        evaluate(&mut p, r, limits()).unwrap().outcome,
        Outcome::NotSelected
    );
    let mut l = limits();
    l.max_input_bytes = 1;
    assert_eq!(
        evaluate(&mut p, request(), l).unwrap().outcome,
        Outcome::Failed(Failure::BudgetExceeded)
    );
    l = limits();
    l.deadline = Instant::now();
    assert_eq!(
        evaluate(&mut p, request(), l).unwrap().outcome,
        Outcome::Failed(Failure::Timeout)
    );
    assert_eq!(p.calls, 0);
}
#[test]
fn rejects_duplicate_choices() {
    let mut r = request();
    r.candidates[1].id = "original".into();
    let mut p = fixture();
    assert_eq!(evaluate(&mut p, r, limits()), Err(Failure::InvalidRequest));
    assert_eq!(p.calls, 0);
}
#[test]
fn malformed_outputs_never_succeed() {
    let mut cases = vec![];
    let mut o = observation();
    o.scores.swap(0, 1);
    cases.push(o);
    let mut o = observation();
    o.scores[0].option_probability = f64::NAN;
    cases.push(o);
    let mut o = observation();
    o.scores[0].option_probability = 0.5;
    cases.push(o);
    let mut o = observation();
    o.judgment = Judgment::Selected {
        candidate_id: "invented".into(),
    };
    cases.push(o);
    let mut o = observation();
    o.judgment = Judgment::Selected {
        candidate_id: "alternative".into(),
    };
    cases.push(o);
    let mut o = observation();
    o.artifacts[0].sha256 = "alias".into();
    cases.push(o);
    for o in cases {
        let mut p = Fixture {
            calls: 0,
            result: Ok(o),
        };
        assert_eq!(
            evaluate(&mut p, request(), limits()).unwrap().outcome,
            Outcome::Failed(Failure::InvalidOutput)
        );
    }
}
#[test]
fn abstention_and_failure_are_distinct() {
    let mut p = fixture();
    p.result.as_mut().unwrap().judgment = Judgment::Abstained;
    assert!(matches!(
        evaluate(&mut p, request(), limits()).unwrap().outcome,
        Outcome::Completed(Observation {
            judgment: Judgment::Abstained,
            ..
        })
    ));
    p.result = Err(Failure::Unavailable);
    assert_eq!(
        evaluate(&mut p, request(), limits()).unwrap().outcome,
        Outcome::Failed(Failure::Unavailable)
    );
}
#[test]
fn rejects_excess_actual_usage() {
    let mut p = fixture();
    p.result.as_mut().unwrap().forwards = 2;
    assert_eq!(
        evaluate(&mut p, request(), limits()).unwrap().outcome,
        Outcome::Failed(Failure::BudgetExceeded)
    );
}
#[test]
fn late_result_is_discarded() {
    struct Late;
    impl DecisionProvider for Late {
        fn decide(&mut self, _: &DecisionRequest, l: Limits) -> Result<Observation, Failure> {
            while Instant::now() < l.deadline {
                std::thread::yield_now();
            }
            Ok(observation())
        }
    }
    let mut l = limits();
    l.deadline = Instant::now() + Duration::from_millis(20);
    assert_eq!(
        evaluate(&mut Late, request(), l).unwrap().outcome,
        Outcome::Failed(Failure::Timeout)
    );
}

#[test]
fn clockless_validation_matches_limits_validation() {
    let request = request();
    let limits = limits();
    let mut wrong_order = observation();
    wrong_order.scores.reverse();
    let mut over_budget = observation();
    over_budget.input_tokens = 129;
    let mut extra_forward = observation();
    extra_forward.forwards = 2;
    for case in [observation(), wrong_order, over_budget, extra_forward] {
        assert_eq!(
            case.validate_within(&request, limits.max_input_tokens, limits.max_forwards),
            case.validate(&request, limits)
        );
    }
    assert_eq!(observation().validate_within(&request, 128, 1), Ok(()));
    let mut over = observation();
    over.input_tokens = 129;
    assert_eq!(
        over.validate_within(&request, 128, 1),
        Err(Failure::BudgetExceeded)
    );
}
