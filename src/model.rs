//! Native inference from a verified bundle on disk.
use crate::{
    bundle::{self, Bundle},
    decide::{check_request, Decider},
    manifest::Manifest,
    tokenize::Tokenizer,
    Artifact, DecisionProvider, DecisionRequest, Error, ErrorKind, Failure, Limits, Observation,
};
use candle_core::safetensors::MmapedSafetensors;
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

/// How [`Model::load`] verifies a bundle.
#[derive(Debug, Clone, Default)]
pub struct LoadOptions {
    /// Give up (with [`ErrorKind::Timeout`]) when hashing and loading are not finished by then.
    /// `None` waits as long as needed.
    pub deadline: Option<Instant>,
    /// Also require that the manifest was locked by this exact build of the library
    /// ([`runtime_build_hash`](crate::runtime_build_hash)). Checkpoint hashes, the prompt
    /// contract, the decision config and the tokenizer are always verified.
    pub require_runtime_build: bool,
}

/// A verified model bundle with its tokenizer and memory-mapped weights, reused across
/// decisions.
///
/// The checkpoint files are memory-mapped after their hashes are checked; they must not be
/// modified or replaced while the `Model` exists.
pub struct Model {
    bundle: Bundle,
    tokenizer: Tokenizer,
    weights: MmapedSafetensors,
    readout: MmapedSafetensors,
    runtime: Artifact,
}

/// Sets the process-wide compute thread count (`RAYON_NUM_THREADS` and `CANDLE_NUM_THREADS`).
///
/// Call it once at the start of the program, before any other thread or any inference: the
/// thread pool is created on first use and keeps its size. [`Model`] refuses to run when the
/// configured count differs from the bundle policy's `cpu_threads`.
pub fn configure_threads(threads: usize) -> Result<(), Error> {
    if !(1..=256).contains(&threads) {
        return Err(Error::new(
            ErrorKind::InvalidArgument,
            "threads must be 1..=256",
        ));
    }
    std::env::set_var("RAYON_NUM_THREADS", threads.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", threads.to_string());
    Ok(())
}

fn threads_match(threads: usize) -> bool {
    candle_core::utils::get_num_threads() == threads
        && std::env::var("CANDLE_NUM_THREADS")
            .ok()
            .and_then(|s| s.parse::<usize>().ok())
            == Some(threads)
}

/// Request checks of a Native decision, in the order of the worker contract.
fn precheck(request: &DecisionRequest, limits: &Limits) -> Result<(), Failure> {
    check_request(request)?;
    if serde_json::to_vec(request)
        .map_err(|_| Failure::InvalidRequest)?
        .len()
        > limits.max_input_bytes
        || limits.max_input_tokens == 0
        || limits.max_forwards == 0
    {
        return Err(Failure::BudgetExceeded);
    }
    if Instant::now() >= limits.deadline {
        return Err(Failure::Timeout);
    }
    Ok(())
}

impl Model {
    /// Verifies the bundle manifest at `manifest` (schema, policy, prompt contract, the set and
    /// SHA-256 of all checkpoint files, tensor names/shapes/dtypes, decision config and the
    /// tokenizer's answer vocabulary), checks the compute threads against the policy and maps
    /// the weights.
    pub fn load(manifest: impl AsRef<Path>, options: &LoadOptions) -> Result<Self, Error> {
        let deadline = options
            .deadline
            .unwrap_or_else(|| Instant::now() + Duration::from_secs(365 * 24 * 3600));
        let bundle = Bundle::verify(manifest.as_ref(), deadline, options.require_runtime_build)
            .map_err(|e| Error::bundle(e, deadline))?;
        // Thread pools are process-wide: callers configure them before loading.
        if !threads_match(bundle.manifest.policy.cpu_threads) {
            return Err(Error::new(
                ErrorKind::ThreadConfig,
                format!(
                    "compute threads must equal the policy's cpu_threads ({}); call configure_threads first",
                    bundle.manifest.policy.cpu_threads
                ),
            ));
        }
        let tokenizer = Tokenizer::load(&bundle).map_err(|e| Error::bundle(e, deadline))?;
        // SAFETY: regular local files whose hashes were just verified; the caller must keep
        // them unchanged while the model exists (documented on `Model`).
        let map = |name: &str| unsafe { MmapedSafetensors::new(bundle.root.join(name)) };
        let weights = map("model.safetensors").map_err(|e| Error::bundle(e.into(), deadline))?;
        let readout = map("readout.safetensors").map_err(|e| Error::bundle(e.into(), deadline))?;
        bundle::check_time(deadline).map_err(|e| Error::bundle(e, deadline))?;
        Ok(Self {
            bundle,
            tokenizer,
            weights,
            readout,
            runtime: Artifact {
                component: "runtime_build".into(),
                sha256: crate::runtime_build_hash(),
            },
        })
    }

    /// One decision. Checks the request (supported question, at most 255 candidates), the byte,
    /// token and forward budgets and the deadline before the forward, and the deadline between
    /// steps; a deadline cannot interrupt a running matrix operation. The observation lists the
    /// bundle files, the manifest, this build, the prompt contract, the rendered prompt and the
    /// policy as artifacts.
    pub fn decide(
        &self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        precheck(request, &limits)?;
        if !threads_match(self.bundle.manifest.policy.cpu_threads) {
            return Err(Failure::Unavailable);
        }
        let expired = || Instant::now() >= limits.deadline;
        let observation = Decider {
            manifest: &self.bundle.manifest,
            manifest_sha256: &self.bundle.manifest_sha256,
            runtime: &self.runtime,
            config: &self.bundle.decision,
            tokenizer: &self.tokenizer,
            weights: &self.weights,
            readout: &self.readout,
        }
        .decide(request, limits.max_input_tokens, &expired, &mut |_| {})?;
        observation.validate(request, limits)?;
        if expired() {
            return Err(Failure::Timeout);
        }
        Ok(observation)
    }

    pub fn manifest(&self) -> &Manifest {
        &self.bundle.manifest
    }

    /// SHA-256 of the manifest file as verified.
    pub fn manifest_sha256(&self) -> &str {
        &self.bundle.manifest_sha256
    }

    /// The checkpoint directory (canonical path).
    pub fn checkpoint_dir(&self) -> &Path {
        &self.bundle.root
    }
}

impl DecisionProvider for Model {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        Model::decide(self, request, limits)
    }
}

impl DecisionProvider for &Model {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        Model::decide(self, request, limits)
    }
}

/// Verifies and loads the bundle inside every call, within that call's deadline, then decides
/// once (the one-request-per-process worker). Loading failures are `Unavailable`, or `Timeout`
/// when the deadline has passed.
pub struct ColdProvider {
    manifest: PathBuf,
    require_runtime_build: bool,
}

impl ColdProvider {
    pub fn new(manifest: impl Into<PathBuf>) -> Self {
        Self {
            manifest: manifest.into(),
            require_runtime_build: false,
        }
    }
    /// See [`LoadOptions::require_runtime_build`].
    pub fn require_runtime_build(mut self, required: bool) -> Self {
        self.require_runtime_build = required;
        self
    }
}

impl DecisionProvider for ColdProvider {
    fn decide(
        &mut self,
        request: &DecisionRequest,
        limits: Limits,
    ) -> Result<Observation, Failure> {
        precheck(request, &limits)?;
        let options = LoadOptions {
            deadline: Some(limits.deadline),
            require_runtime_build: self.require_runtime_build,
        };
        let model = Model::load(&self.manifest, &options).map_err(|e| {
            if e.kind() == ErrorKind::Timeout || Instant::now() >= limits.deadline {
                Failure::Timeout
            } else {
                Failure::Unavailable
            }
        })?;
        model.decide(request, limits)
    }
}
