use serde_json::{json, Value};
use std::{path::Path, process::Command};
fn wire() -> Value {
    json!({"schema_version":"kaze_judge.worker.v1",
        "request":serde_json::from_slice::<Value>(include_bytes!("../../../examples/candidate-request.json")).unwrap(),
        "max_input_tokens":512,"max_forwards":1,"timeout_ms":10000})
}
fn invoke(dir: &Path, wire: &[u8]) -> std::process::Output {
    let input = dir.join("request.json");
    std::fs::write(&input, wire).unwrap();
    Command::new(env!("CARGO_BIN_EXE_jeff"))
        .arg("worker")
        .arg("--manifest")
        .arg(dir.join("missing.json"))
        .arg("--request")
        .arg(input)
        .arg("--response")
        .arg(dir.join("response.json"))
        .output()
        .unwrap()
}
#[test]
fn worker_preflight_and_unavailable_are_typed_responses() {
    for (field, value, failure) in [
        ("max_forwards", 0, "budget_exceeded"),
        ("max_input_tokens", 0, "budget_exceeded"),
        ("timeout_ms", 0, "timeout"),
        ("max_input_tokens", 512, "unavailable"),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let mut request = wire();
        request[field] = json!(value);
        assert!(invoke(dir.path(), &serde_json::to_vec(&request).unwrap())
            .status
            .success());
        let output: Value =
            serde_json::from_slice(&std::fs::read(dir.path().join("response.json")).unwrap())
                .unwrap();
        assert_eq!(output["schema_version"], "kaze_judge.worker.v1");
        assert_eq!(output["request_id"], request["request"]["request_id"]);
        assert_eq!(output["result"], json!({"status":"failed","value":failure}));
    }
}
#[test]
fn malformed_worker_inputs_and_existing_output_are_rejected() {
    let mut bad_schema = wire();
    bad_schema["schema_version"] = json!("unknown");
    let mut extra = wire();
    extra["extra"] = json!(true);
    for input in [
        serde_json::to_vec(&bad_schema).unwrap(),
        serde_json::to_vec(&extra).unwrap(),
        br#"{"schema_version":"a","schema_version":"b"}"#.to_vec(),
    ] {
        let dir = tempfile::tempdir().unwrap();
        assert!(!invoke(dir.path(), &input).status.success());
        assert!(!dir.path().join("response.json").exists());
    }
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("response.json"), "preserve").unwrap();
    assert!(!invoke(dir.path(), &serde_json::to_vec(&wire()).unwrap())
        .status
        .success());
    assert_eq!(
        std::fs::read_to_string(dir.path().join("response.json")).unwrap(),
        "preserve"
    );
}
#[test]
fn process_cli_opt_out_needs_no_manifest() {
    let dir = tempfile::tempdir().unwrap();
    let mut request = wire()["request"].clone();
    request["reason"] = Value::Null;
    let path = dir.path().join("request.json");
    std::fs::write(&path, serde_json::to_vec(&request).unwrap()).unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_jeff"))
        .arg("decide-process")
        .arg(dir.path().join("missing.json"))
        .arg(path)
        .args(["10000", "512"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let attempt: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(attempt["provider_calls_started"], 0);
    assert_eq!(attempt["outcome"]["status"], "not_selected");
}
