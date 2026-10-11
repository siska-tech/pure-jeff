use kaze_judge::{DecisionProvider, DecisionRequest, Failure, Judgment, Limits};
use kaze_judge_jeff::{json, policy::Policy, prompt, RustProvider};
use serde_json::Value;
use std::time::{Duration, Instant};
const GOLDENS: [&[u8]; 7] = [
    include_bytes!("../../../tests/fixtures/jeff-golden/candidate-request.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/reversed.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/asr-unicode.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/long-text.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/special-token-text.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/maximum-candidates.json"),
    include_bytes!("../../../tests/fixtures/jeff-golden/token-limit-8192.json"),
];
fn request() -> DecisionRequest {
    let g: Value = json::parse(GOLDENS[0]).unwrap();
    serde_json::from_value(g["request"].clone()).unwrap()
}
#[test]
fn independent_prompt_bytes_match_all_official_goldens() {
    for bytes in GOLDENS {
        let g: Value = json::parse(bytes).unwrap();
        let r: DecisionRequest = serde_json::from_value(g["request"].clone()).unwrap();
        let codes: Vec<String> = serde_json::from_value(g["codes"].clone()).unwrap();
        for layout in ["state-first", "live-last"] {
            assert_eq!(
                prompt::render(&r, &codes, layout).unwrap(),
                g["prompt"].as_str().unwrap()
            );
        }
        assert!(prompt::render(&r, &codes, "unknown").is_err());
    }
}
#[test]
fn selection_boundaries_and_invalid_distributions() {
    let r = request();
    let p = Policy {
        min_probability: 0.8,
        min_margin: 0.8 - 0.2,
        cpu_threads: 1,
    };
    assert!(matches!(
        p.judge(&r, &[0.8, 0.2]).unwrap(),
        Judgment::Selected { .. }
    ));
    let higher = Policy {
        min_probability: 0.8_f64.next_up(),
        ..p.clone()
    };
    assert_eq!(higher.judge(&r, &[0.8, 0.2]).unwrap(), Judgment::Abstained);
    let higher = Policy {
        min_margin: (0.8_f64 - 0.2).next_up(),
        ..p.clone()
    };
    assert_eq!(higher.judge(&r, &[0.8, 0.2]).unwrap(), Judgment::Abstained);
    let zero = Policy {
        min_probability: 0.0,
        min_margin: 0.0,
        ..p
    };
    assert_eq!(zero.judge(&r, &[0.5, 0.5]).unwrap(), Judgment::Abstained);
    for bad in [
        vec![f64::NAN, 0.2],
        vec![0.8, 0.3],
        vec![1.0],
        vec![-0.1, 1.1],
    ] {
        assert!(zero.judge(&r, &bad).is_err());
    }
}
#[test]
fn preflight_stops_without_loading_a_missing_bundle() {
    let mut provider = RustProvider::new("nonexistent-bundle.json");
    let mut r = request();
    let limits = Limits {
        max_input_bytes: 1_000_000,
        max_input_tokens: 512,
        max_forwards: 1,
        deadline: Instant::now() + Duration::from_secs(10),
    };
    for l in [
        Limits {
            max_input_tokens: 0,
            ..limits
        },
        Limits {
            max_forwards: 0,
            ..limits
        },
        Limits {
            max_input_bytes: 1,
            ..limits
        },
    ] {
        assert_eq!(provider.decide(&r, l), Err(Failure::BudgetExceeded));
    }
    assert_eq!(
        provider.decide(
            &r,
            Limits {
                deadline: Instant::now(),
                ..limits
            }
        ),
        Err(Failure::Timeout)
    );
    r.reason = None;
    assert_eq!(provider.decide(&r, limits), Err(Failure::InvalidRequest));
}
