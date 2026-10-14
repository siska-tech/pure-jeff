//! Standalone std-only stand-in for the Python interpreter, compiled by process_launch.rs and
//! started by `LocalProcessProvider` exactly as Python would be. It checks the launcher's
//! command line and environment (exit 3 if they differ), then acts on the request's
//! `original_text`:
//!   `slow_start_ms=N`  sleep N ms before doing anything (a slow interpreter start-up), then
//!                      write `<manifest>.started` and a valid response
//!   `timeout`          write `.started`, sleep 3 s, write `.survived` (must be killed first)
//!   `late_exit`        write a valid response, sleep 3 s, write `.survived`
use std::{env, fs, process, thread, time::Duration};

fn main() {
    let args: Vec<String> = env::args().collect();
    // python -I -B <worker> --manifest M --request R --response O
    let ok = args.len() == 10
        && args[1] == "-I"
        && args[2] == "-B"
        && args[4] == "--manifest"
        && args[6] == "--request"
        && args[8] == "--response"
        && env::var("HF_HUB_OFFLINE").as_deref() == Ok("1")
        && env::var("TRANSFORMERS_OFFLINE").as_deref() == Ok("1");
    if !ok {
        process::exit(3);
    }
    let (manifest, response) = (&args[5], &args[9]);
    let request = fs::read_to_string(&args[7]).unwrap();
    let mode = request
        .split("\"original_text\":\"")
        .nth(1)
        .and_then(|rest| rest.split('"').next())
        .unwrap_or("")
        .to_owned();
    let marker = |name: &str| fs::write(format!("{manifest}.{name}"), process::id().to_string()).unwrap();
    let respond = || {
        let observation = format!(
            r#"{{"scores":[{{"candidate_id":"first","option_probability":0.8}},{{"candidate_id":"second","option_probability":0.2}}],"judgment":{{"kind":"selected","candidate_id":"first"}},"temperature":1.0,"input_tokens":10,"forwards":1,"artifacts":[{{"component":"fixture","sha256":"{}"}}]}}"#,
            "a".repeat(64)
        );
        fs::write(
            response,
            format!(r#"{{"schema_version":"pure_jeff.worker.v1","request_id":"request","result":{{"status":"completed","value":{observation}}}}}"#),
        )
        .unwrap();
    };
    if let Some(ms) = mode.strip_prefix("slow_start_ms=") {
        thread::sleep(Duration::from_millis(ms.parse().unwrap()));
        marker("started");
        respond();
    } else if mode == "timeout" {
        marker("started");
        thread::sleep(Duration::from_secs(3));
        marker("survived");
    } else if mode == "late_exit" {
        marker("started");
        respond();
        thread::sleep(Duration::from_secs(3));
        marker("survived");
    } else {
        process::exit(4);
    }
}
