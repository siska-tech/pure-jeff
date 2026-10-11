//! Standalone std-only test worker, compiled by native_process.rs.
use std::{fs, thread, time::Duration};
fn main() {
    let args: Vec<_> = std::env::args().collect();
    assert_eq!(args.len(), 8);
    assert_eq!(args[1], "worker");
    let request = fs::read_to_string(&args[5]).unwrap();
    fs::write(format!("{}.started", args[3]), "started").unwrap();
    let is = |mode| request.contains(&format!("\"original_text\":\"{mode}\""));
    if is("crash") { std::process::exit(1); }
    if is("timeout") {
        thread::sleep(Duration::from_secs(2));
        fs::write(format!("{}.survived", args[3]), "survived").unwrap();
    }
    let result = if is("invalid_json") { "{".into() }
        else if is("oversized") { "x".repeat(1_048_577) }
        else {
            let id = if is("wrong_id") { "wrong" } else { "request" };
            let result = if is("unavailable") { r#"{"status":"failed","value":"unavailable"}"#.into() }
                else if is("budget") { r#"{"status":"failed","value":"budget_exceeded"}"#.into() }
                else { format!(r#"{{"status":"completed","value":{{"scores":[{{"candidate_id":"first","option_probability":0.8}},{{"candidate_id":"second","option_probability":0.2}}],"judgment":{{"kind":"selected","candidate_id":"first"}},"temperature":1.0,"input_tokens":10,"forwards":1,"artifacts":[{{"component":"fixture","sha256":"{}"}}]}}}}"#, "a".repeat(64)) };
            if is("duplicate_key") {
                format!(r#"{{"schema_version":"kaze_judge.worker.v1","request_id":"wrong","request_id":"{id}","result":{result}}}"#)
            } else {
                let schema = if is("wrong_schema") { "wrong" } else { "kaze_judge.worker.v1" };
                format!(r#"{{"schema_version":"{schema}","request_id":"{id}","result":{result}}}"#)
            }
        };
    fs::write(&args[7], result).unwrap();
    if is("late_exit") {
        thread::sleep(Duration::from_secs(2));
        fs::write(format!("{}.survived", args[3]), "survived").unwrap();
    }
}
