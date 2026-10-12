//! Pure-Rust CPU inference for the Jeff-Qwen3.5-0.8B candidate decision model.
//!
//! Given an original recognized text and 2–255 transcription candidates, the model returns a
//! distribution over the supplied candidates and a decision: one candidate is *selected*, or
//! the call *abstains*. The distribution compares the supplied choices only; it is not a
//! probability that any candidate is a correct transcription.
//!
//! The model files are not part of this crate. A *bundle manifest* fixes the SHA-256 of every
//! checkpoint file, the selection policy and the prompt; [`lock`] writes one for a downloaded
//! checkpoint and [`Model::load`] verifies it before anything is read.
//!
//! ```no_run
//! use pure_jeff::{DecisionRequest, Limits, LoadOptions, Model};
//! use std::time::{Duration, Instant};
//!
//! # fn main() -> Result<(), Box<dyn std::error::Error>> {
//! // Process-wide compute threads; must equal the bundle policy and precede any inference.
//! pure_jeff::configure_threads(1)?;
//! let model = Model::load("models/jeff-bundle.json", &LoadOptions::default())?;
//! let request: DecisionRequest = serde_json::from_str(&std::fs::read_to_string("request.json")?)?;
//! let limits = Limits {
//!     max_input_bytes: 1024 * 1024,
//!     max_input_tokens: 8192,
//!     max_forwards: 1,
//!     deadline: Instant::now() + Duration::from_secs(600),
//! };
//! let observation = model.decide(&request, limits)?;
//! println!("{:?}", observation.judgment);
//! # Ok(())
//! # }
//! ```
//!
//! Only the fixed checkpoint `jeff-legacy/Jeff-Qwen3.5-0.8B` (text only, batch one, at most
//! 8192 input tokens, FP32 compute) is supported.
mod contract;
mod decide;
mod error;
mod manifest;
pub mod policy;
pub mod prompt;

pub mod memory;

#[doc(hidden)]
pub mod backbone;
#[doc(hidden)]
pub mod config;
#[doc(hidden)]
pub mod json;
#[doc(hidden)]
pub mod readout;
#[doc(hidden)]
pub mod tokenize;

#[cfg(feature = "native")]
pub mod bundle;
#[cfg(feature = "native")]
mod model;
#[cfg(feature = "process")]
mod process;
#[cfg(feature = "process")]
pub mod worker;

pub use contract::{
    evaluate, Artifact, Attempt, Candidate, CandidateScore, DecisionProvider, DecisionRequest,
    Failure, Judgment, Limits, Observation, Outcome, RoutingReason, Source, ATTEMPT_SCHEMA,
};
pub use error::{Error, ErrorKind};
pub use manifest::{FileRecord, Manifest, SCHEMA as BUNDLE_SCHEMA};
pub use policy::Policy;

#[cfg(feature = "native")]
pub use bundle::lock;
#[cfg(feature = "native")]
pub use model::{configure_threads, ColdProvider, LoadOptions, Model};
#[cfg(feature = "process")]
pub use process::{LocalProcessProvider, NativeProcessProvider};

/// SHA-256 identifying this build of the library: its sources, the tensor specification and
/// the compiler, target, profile and flags. Recorded as the `runtime_build` artifact of every
/// Native observation and in bundles written by [`lock`].
pub fn runtime_build_hash() -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    for source in SOURCES.iter().map(|(_, bytes)| *bytes).chain([
        include_bytes!("../Cargo.toml").as_slice(),
        include_bytes!("../build.rs"),
        include_bytes!("../spec/jeff-0.8b-tensors.json"),
        env!("PURE_JEFF_BUILD_INFO").as_bytes(),
    ]) {
        h.update(Sha256::digest(source));
    }
    format!("{:x}", h.finalize())
}

/// Every source file of the library, in a fixed order (a test checks the list is complete).
const SOURCES: [(&str, &[u8]); 18] = [
    ("lib.rs", include_bytes!("lib.rs")),
    ("contract.rs", include_bytes!("contract.rs")),
    ("decide.rs", include_bytes!("decide.rs")),
    ("error.rs", include_bytes!("error.rs")),
    ("manifest.rs", include_bytes!("manifest.rs")),
    ("policy.rs", include_bytes!("policy.rs")),
    ("prompt.rs", include_bytes!("prompt.rs")),
    ("memory.rs", include_bytes!("memory.rs")),
    ("backbone.rs", include_bytes!("backbone.rs")),
    ("config.rs", include_bytes!("config.rs")),
    ("json.rs", include_bytes!("json.rs")),
    ("readout.rs", include_bytes!("readout.rs")),
    ("tokenize.rs", include_bytes!("tokenize.rs")),
    ("weights.rs", include_bytes!("weights.rs")),
    ("bundle.rs", include_bytes!("bundle.rs")),
    ("model.rs", include_bytes!("model.rs")),
    ("process.rs", include_bytes!("process.rs")),
    ("worker.rs", include_bytes!("worker.rs")),
];

mod weights;
#[doc(hidden)]
pub use weights::Retained;
pub use weights::WeightSource;

#[cfg(test)]
mod tests {
    #[test]
    fn build_hash_covers_every_source_file() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut files: Vec<String> = std::fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().into_string().unwrap())
            .filter(|n| n.ends_with(".rs"))
            .collect();
        files.sort();
        let mut listed: Vec<String> = super::SOURCES.iter().map(|(n, _)| n.to_string()).collect();
        listed.sort();
        assert_eq!(files, listed);
    }
}
