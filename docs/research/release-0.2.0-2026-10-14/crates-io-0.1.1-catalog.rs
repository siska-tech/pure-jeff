//! Decides the exported catalog inputs with pure-jeff 0.1.1 from crates.io and writes
//! {"id", "probability_bits", "judgment"} lines.
use pure_jeff::{DecisionRequest, Limits, LoadOptions, Model};
use std::io::Write;
use std::time::{Duration, Instant};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    pure_jeff::configure_threads(1).unwrap();
    let model = Model::load(&args[1], &LoadOptions::default()).unwrap();
    let cases: Vec<serde_json::Value> = serde_json::from_slice(&std::fs::read(&args[2]).unwrap()).unwrap();
    let mut out = std::fs::File::create_new(&args[3]).unwrap();
    for case in &cases {
        let request: DecisionRequest = serde_json::from_value(case["request"].clone()).unwrap();
        let limits = Limits { max_input_bytes: 1 << 20, max_input_tokens: 8192, max_forwards: 1,
                              deadline: Instant::now() + Duration::from_secs(1800) };
        let line = match model.decide(&request, limits) {
            Ok(o) => serde_json::json!({"id": case["id"], "probability_bits":
                o.scores.iter().map(|s| format!("{:016x}", s.option_probability.to_bits())).collect::<Vec<_>>(),
                "judgment": o.judgment}),
            Err(f) => serde_json::json!({"id": case["id"], "failure": f}),
        };
        writeln!(out, "{line}").unwrap();
    }
}
