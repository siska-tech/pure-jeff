//! One-shot local process boundary. No shell, network client or automatic retry.
use crate::{
    worker::WORKER_SCHEMA, DecisionProvider, DecisionRequest, Failure, Limits, Observation,
};
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    io::Read,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

/// Starts a trusted Python worker for each call. Model loading is part of the deadline.
/// The worker must not launch descendants; termination covers the direct child only.
pub struct LocalProcessProvider {
    inner: ProcessProvider,
}
/// Starts a trusted Rust worker executable; Python is not involved.
/// The executable accepts `worker --manifest ... --request ... --response ...` and speaks
/// [`WORKER_SCHEMA`](crate::worker::WORKER_SCHEMA); [`worker::run`](crate::worker::run) implements it.
/// As with LocalProcessProvider, termination covers only the direct child.
pub struct NativeProcessProvider {
    inner: ProcessProvider,
}
enum Launcher {
    Python { python: PathBuf, worker: PathBuf },
    Native { executable: PathBuf },
}
struct ProcessProvider {
    launcher: Launcher,
    manifest: PathBuf,
    max_response_bytes: u64,
}
#[derive(Serialize)]
struct WireRequest<'a> {
    schema_version: &'static str,
    request: &'a DecisionRequest,
    max_input_tokens: usize,
    max_forwards: usize,
    timeout_ms: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WireResponse {
    schema_version: String,
    request_id: String,
    result: WorkerResult,
}
#[derive(Deserialize)]
#[serde(
    tag = "status",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
enum WorkerResult {
    Completed(Observation),
    Failed(Failure),
}
struct RunningChild(Child);
impl Drop for RunningChild {
    fn drop(&mut self) {
        // Covers early returns, including invalid output and interrupted polling.
        if !matches!(self.0.try_wait(), Ok(Some(_))) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
impl LocalProcessProvider {
    pub fn new(
        python: impl AsRef<Path>,
        worker: impl AsRef<Path>,
        manifest: impl AsRef<Path>,
    ) -> Result<Self, Failure> {
        Ok(Self {
            inner: ProcessProvider {
                launcher: Launcher::Python {
                    python: local(python.as_ref())?,
                    worker: local(worker.as_ref())?,
                },
                manifest: local(manifest.as_ref())?,
                max_response_bytes: 1_048_576,
            },
        })
    }
}
fn local(path: &Path) -> Result<PathBuf, Failure> {
    let path = path.canonicalize().map_err(|_| Failure::Unavailable)?;
    if !path.is_file() {
        return Err(Failure::Unavailable);
    }
    Ok(path)
}
impl NativeProcessProvider {
    pub fn new(executable: impl AsRef<Path>, manifest: impl AsRef<Path>) -> Result<Self, Failure> {
        Ok(Self {
            inner: ProcessProvider {
                launcher: Launcher::Native {
                    executable: local(executable.as_ref())?,
                },
                manifest: local(manifest.as_ref())?,
                max_response_bytes: 1_048_576,
            },
        })
    }
}
impl DecisionProvider for LocalProcessProvider {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        self.inner.decide(request, limits)
    }
}
impl DecisionProvider for NativeProcessProvider {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        self.inner.decide(request, limits)
    }
}
impl DecisionProvider for ProcessProvider {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        request.validate()?;
        if request.reason.is_none() {
            return Err(Failure::InvalidRequest);
        }
        if serde_json::to_vec(request)
            .map_err(|_| Failure::InvalidRequest)?
            .len()
            > limits.max_input_bytes
            || limits.max_input_tokens == 0
            || limits.max_forwards == 0
        {
            return Err(Failure::BudgetExceeded);
        }
        let remaining = limits.deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(Failure::Timeout);
        }
        let exchange = tempfile::Builder::new()
            .prefix("pure-jeff-")
            .tempdir()
            .map_err(|_| Failure::Unavailable)?;
        let input = exchange.path().join("request.json");
        let output = exchange.path().join("response.json");
        let wire = WireRequest {
            schema_version: WORKER_SCHEMA,
            request,
            max_input_tokens: limits.max_input_tokens,
            max_forwards: limits.max_forwards,
            timeout_ms: remaining.as_millis().min(u64::MAX as u128) as u64,
        };
        serde_json::to_writer(
            File::create(&input).map_err(|_| Failure::Unavailable)?,
            &wire,
        )
        .map_err(|_| Failure::Unavailable)?;
        if Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        let mut command = match &self.launcher {
            Launcher::Python { python, worker } => {
                let mut command = Command::new(python);
                command
                    .args(["-I", "-B"])
                    .arg(worker)
                    .env("HF_HUB_OFFLINE", "1")
                    .env("TRANSFORMERS_OFFLINE", "1");
                command
            }
            Launcher::Native { executable } => {
                let mut command = Command::new(executable);
                command.arg("worker");
                command
            }
        };
        command
            .arg("--manifest")
            .arg(&self.manifest)
            .arg("--request")
            .arg(&input)
            .arg("--response")
            .arg(&output)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut child = RunningChild(command.spawn().map_err(|_| Failure::Unavailable)?);
        loop {
            if Instant::now() >= limits.deadline {
                return Err(Failure::Timeout);
            }
            if let Some(status) = child.0.try_wait().map_err(|_| Failure::Unavailable)? {
                if !status.success() {
                    return Err(Failure::Unavailable);
                }
                break;
            }
            thread::sleep(
                Duration::from_millis(5)
                    .min(limits.deadline.saturating_duration_since(Instant::now())),
            );
        }
        let file = File::open(output).map_err(|_| Failure::InvalidOutput)?;
        if !file
            .metadata()
            .map_err(|_| Failure::InvalidOutput)?
            .is_file()
        {
            return Err(Failure::InvalidOutput);
        }
        let mut bytes = Vec::new();
        file.take(self.max_response_bytes + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| Failure::InvalidOutput)?;
        if bytes.len() as u64 > self.max_response_bytes {
            return Err(Failure::InvalidOutput);
        }
        let response: WireResponse =
            serde_json::from_slice(&bytes).map_err(|_| Failure::InvalidOutput)?;
        if Instant::now() >= limits.deadline {
            return Err(Failure::Timeout);
        }
        if response.schema_version != WORKER_SCHEMA || response.request_id != request.request_id {
            return Err(Failure::InvalidOutput);
        }
        match response.result {
            WorkerResult::Completed(observation) => {
                observation.validate(request, limits)?;
                Ok(observation)
            }
            WorkerResult::Failed(error) => Err(error),
        }
    }
}
