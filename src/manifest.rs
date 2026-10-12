//! The bundle manifest format, shared by the file-based and in-memory paths.
use crate::policy::Policy;
use serde::{Deserialize, Serialize};

/// Schema identifier of a bundle manifest.
pub const SCHEMA: &str = "pure_jeff.bundle.v1";
/// One checkpoint file and its SHA-256 (lowercase hex).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FileRecord {
    pub path: String,
    pub sha256: String,
}
/// A bundle manifest ([`SCHEMA`]). `checkpoint_dir` is relative to the manifest's directory;
/// `runtime_build_sha256` is the [`runtime_build_hash`](crate::runtime_build_hash) of the build
/// that wrote it.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub schema_version: String,
    pub checkpoint_dir: String,
    pub checkpoint_revision: String,
    pub files: Vec<FileRecord>,
    pub policy: Policy,
    pub prompt_sha256: String,
    pub runtime_build_sha256: String,
}
