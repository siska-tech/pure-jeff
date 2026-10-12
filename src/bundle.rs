//! Bundle manifests: the SHA-256 of every checkpoint file, the policy and the prompt contract.
use crate::{config::DecisionConfig, json, policy::Policy, Error, ErrorKind};
use anyhow::{ensure, Context, Result};
use candle_core::safetensors::MmapedSafetensors;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path, PathBuf},
    time::Instant,
};

pub use crate::manifest::{FileRecord, Manifest, SCHEMA};
const REQUIRED: [&str; 11] = [
    "LICENSE",
    "NOTICE",
    "README.md",
    "chat_template.jinja",
    "config.json",
    "decision_config.json",
    "model.safetensors",
    "processor_config.json",
    "readout.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
];
const CONFIG_HASH: &str = "e430598ca8aa6228b9856573dcc0425d0710acad4a19a937da52cde724b34f25";
const TEMPLATE_HASH: &str = "273d8e0e683b885071fb17e08d71e5f2a5ddfb5309756181681de4f5a1822d80";
const TOKENIZER_CONFIG_HASH: &str =
    "5f7aa0d810000c4a0940b35c8f16e56c3439260fccc13a321826ebc3ccf2501f";

#[doc(hidden)]
pub fn check_time(deadline: Instant) -> Result<()> {
    ensure!(Instant::now() < deadline, "deadline exceeded");
    Ok(())
}
#[doc(hidden)]
pub fn hash_bytes(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
#[doc(hidden)]
pub fn hash_file(path: &Path, deadline: Instant) -> Result<String> {
    plain(path)?;
    let mut f = File::open(path)?;
    let mut h = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        check_time(deadline)?;
        let n = f.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        h.update(&buffer[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}
/// Reads a JSON file of at most `limit` bytes, rejecting duplicate keys.
#[doc(hidden)]
pub fn read_json<T: serde::de::DeserializeOwned>(path: &Path, limit: u64) -> Result<T> {
    plain(path)?;
    let mut bytes = Vec::new();
    File::open(path)?.take(limit + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() as u64 <= limit, "JSON size limit exceeded");
    Ok(json::parse(&bytes)?)
}
fn plain(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path)?;
    ensure!(!metadata.file_type().is_symlink(), "symlink rejected");
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        ensure!(
            metadata.file_attributes() & 0x400 == 0,
            "reparse point rejected"
        );
    }
    ensure!(
        metadata.is_file() || metadata.is_dir(),
        "not a regular file/directory"
    );
    Ok(())
}
fn relative(path: &Path) -> Result<()> {
    ensure!(
        !path.as_os_str().is_empty()
            && path.components().all(|c| matches!(c, Component::Normal(_))),
        "invalid relative asset path"
    );
    Ok(())
}
fn inventory(root: &Path, deadline: Instant) -> Result<Vec<FileRecord>> {
    fn walk(root: &Path, dir: &Path, out: &mut Vec<FileRecord>, deadline: Instant) -> Result<()> {
        plain(dir)?;
        for entry in fs::read_dir(dir)? {
            check_time(deadline)?;
            let p = entry?.path();
            plain(&p)?;
            if p.is_dir() {
                walk(root, &p, out, deadline)?;
            } else {
                let name = p
                    .strip_prefix(root)?
                    .to_str()
                    .context("non-UTF8 asset path")?
                    .replace('\\', "/");
                out.push(FileRecord {
                    path: name,
                    sha256: hash_file(&p, deadline)?,
                });
            }
        }
        Ok(())
    }
    let mut out = Vec::new();
    walk(root, root, &mut out, deadline)?;
    out.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(out)
}
#[doc(hidden)]
pub struct Bundle {
    pub manifest: Manifest,
    pub root: PathBuf,
    pub manifest_sha256: String,
    pub decision: DecisionConfig,
}
fn validate_records(records: &[FileRecord]) -> Result<()> {
    let names: HashSet<_> = records.iter().map(|r| r.path.as_str()).collect();
    ensure!(
        records.len() == REQUIRED.len() && names == HashSet::from(REQUIRED),
        "unsupported asset file set"
    );
    for r in records {
        relative(Path::new(&r.path))?;
        ensure!(
            r.sha256.len() == 64 && r.sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid asset hash"
        );
    }
    for (name, expected) in [
        ("config.json", CONFIG_HASH),
        ("chat_template.jinja", TEMPLATE_HASH),
        ("tokenizer_config.json", TOKENIZER_CONFIG_HASH),
    ] {
        ensure!(
            records
                .iter()
                .find(|r| r.path == name)
                .context("missing required asset")?
                .sha256
                == expected,
            "unsupported {name}"
        );
    }
    Ok(())
}
#[derive(Deserialize)]
struct TensorSpec {
    shape: Vec<usize>,
    dtype: String,
}
fn validate_tensors(root: &Path) -> Result<()> {
    let specs: BTreeMap<String, BTreeMap<String, TensorSpec>> =
        json::parse(include_bytes!("../spec/jeff-0.8b-tensors.json"))?;
    for (file, spec) in specs {
        validate_tensor_file(&root.join(file), &spec)?;
    }
    Ok(())
}
fn validate_tensor_file(path: &Path, spec: &BTreeMap<String, TensorSpec>) -> Result<()> {
    plain(path)?;
    // SAFETY: regular local file, hashed before validation; caller must keep it immutable.
    let tensors = unsafe { MmapedSafetensors::new(path)? };
    ensure!(
        tensors.tensors().len() == spec.len(),
        "unexpected tensor set"
    );
    for (name, expected) in spec {
        let actual = tensors.get(name)?;
        ensure!(
            actual.shape() == expected.shape && format!("{:?}", actual.dtype()) == expected.dtype,
            "unsupported tensor shape/dtype: {name}"
        );
    }
    Ok(())
}
impl Bundle {
    pub fn lock(
        checkpoint: &Path,
        output: &Path,
        revision: &str,
        policy: Policy,
        deadline: Instant,
    ) -> Result<Self> {
        policy.validate()?;
        ensure!(!output.exists(), "manifest already exists");
        plain(checkpoint)?;
        let root = checkpoint.canonicalize()?;
        let parent = output
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."))
            .canonicalize()?;
        let checkpoint_dir = root
            .strip_prefix(&parent)
            .context("manifest must be outside and above the checkpoint directory")?;
        relative(checkpoint_dir)?;
        ensure!(
            revision.len() == 40 && revision.bytes().all(|b| b.is_ascii_hexdigit()),
            "immutable checkpoint revision required"
        );
        let files = inventory(&root, deadline)?;
        validate_records(&files)?;
        let decision: DecisionConfig = read_json(&root.join("decision_config.json"), 1024 * 1024)?;
        decision.validate()?;
        let manifest = Manifest {
            schema_version: SCHEMA.into(),
            checkpoint_dir: checkpoint_dir
                .to_str()
                .context("non-UTF8 checkpoint path")?
                .replace('\\', "/"),
            checkpoint_revision: revision.into(),
            files,
            policy,
            prompt_sha256: hash_bytes(include_bytes!("prompt.rs")),
            runtime_build_sha256: crate::runtime_build_hash(),
        };
        let bundle = Self {
            manifest,
            root,
            manifest_sha256: String::new(),
            decision,
        };
        validate_tensors(&bundle.root)?;
        crate::tokenize::Tokenizer::load(&bundle)?;
        check_time(deadline)?;
        let mut bytes = serde_json::to_vec_pretty(&bundle.manifest)?;
        bytes.push(b'\n');
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output)?
            .write_all(&bytes)?;
        Ok(Self {
            manifest_sha256: hash_bytes(&bytes),
            ..bundle
        })
    }
    /// Verifies the manifest and every checkpoint file. The prompt contract must match this
    /// library; the build that wrote the manifest must match only with `require_runtime_build`.
    pub fn verify(path: &Path, deadline: Instant, require_runtime_build: bool) -> Result<Self> {
        check_time(deadline)?;
        let manifest: Manifest = read_json(path, 2 * 1024 * 1024)?;
        ensure!(
            manifest.schema_version == SCHEMA
                && manifest.prompt_sha256 == hash_bytes(include_bytes!("prompt.rs")),
            "unsupported manifest/prompt"
        );
        ensure!(
            !require_runtime_build || manifest.runtime_build_sha256 == crate::runtime_build_hash(),
            "manifest was locked by a different runtime build"
        );
        manifest.policy.validate()?;
        validate_records(&manifest.files)?;
        relative(Path::new(&manifest.checkpoint_dir))?;
        ensure!(
            manifest.checkpoint_revision.len() == 40
                && manifest
                    .checkpoint_revision
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit()),
            "invalid checkpoint revision"
        );
        let parent = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."))
            .canonicalize()?;
        let mut root = parent.clone();
        for part in Path::new(&manifest.checkpoint_dir).components() {
            root.push(part);
            plain(&root)?;
        }
        let root = root.canonicalize()?;
        ensure!(
            root.starts_with(parent),
            "checkpoint escapes manifest directory"
        );
        ensure!(
            inventory(&root, deadline)? == manifest.files,
            "checkpoint file set or hashes changed"
        );
        let decision: DecisionConfig = read_json(&root.join("decision_config.json"), 1024 * 1024)?;
        decision.validate()?;
        validate_tensors(&root)?;
        check_time(deadline)?;
        Ok(Self {
            manifest,
            root,
            manifest_sha256: hash_file(path, deadline)?,
            decision,
        })
    }
}

/// Writes a new bundle manifest for a downloaded checkpoint directory and returns the
/// manifest's SHA-256. The manifest must not exist yet and must be placed outside and above the
/// checkpoint directory; `revision` is the checkpoint's immutable 40-hex revision. Every file
/// is hashed and the tensor set, decision config and tokenizer are checked first.
pub fn lock(
    checkpoint: impl AsRef<Path>,
    manifest: impl AsRef<Path>,
    revision: &str,
    policy: Policy,
    deadline: Instant,
) -> std::result::Result<String, Error> {
    if policy.validate().is_err() {
        return Err(Error::new(ErrorKind::InvalidArgument, "invalid policy"));
    }
    Bundle::lock(
        checkpoint.as_ref(),
        manifest.as_ref(),
        revision,
        policy,
        deadline,
    )
    .map(|bundle| bundle.manifest_sha256)
    .map_err(|e| Error::bundle(e, deadline))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    fn deadline() -> Instant {
        Instant::now() + Duration::from_secs(10)
    }
    #[test]
    fn inventory_detects_added_modified_and_missing_files() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let p = dir.path().join("asset");
        fs::write(&p, "a")?;
        let original = inventory(dir.path(), deadline())?;
        fs::write(&p, "b")?;
        assert_ne!(original, inventory(dir.path(), deadline())?);
        fs::write(dir.path().join("extra"), "c")?;
        assert_eq!(inventory(dir.path(), deadline())?.len(), 2);
        fs::remove_file(&p)?;
        assert_ne!(original, inventory(dir.path(), deadline())?);
        Ok(())
    }
    #[test]
    fn paths_deadlines_and_required_sets_are_enforced() {
        for p in ["", "../model", "/model", "a/../b"] {
            assert!(relative(Path::new(p)).is_err(), "{p}");
        }
        // A drive prefix is absolute only on Windows; elsewhere `C:\model` is one plain name.
        assert_eq!(relative(Path::new("C:\\model")).is_err(), cfg!(windows));
        assert!(validate_records(&[]).is_err());
        assert!(check_time(Instant::now()).is_err());
    }
    #[test]
    fn tensor_names_shapes_and_dtypes_are_checked() -> Result<()> {
        use candle_core::{DType, Device, Tensor};
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("test.safetensors");
        let tensors = std::collections::HashMap::from([(
            "weight",
            Tensor::zeros((2, 2), DType::F32, &Device::Cpu)?,
        )]);
        candle_core::safetensors::save(&tensors, &path)?;
        let good = BTreeMap::from([(
            "weight".into(),
            TensorSpec {
                shape: vec![2, 2],
                dtype: "F32".into(),
            },
        )]);
        validate_tensor_file(&path, &good)?;
        for (name, shape, dtype) in [
            ("weight", vec![2, 3], "F32"),
            ("weight", vec![2, 2], "BF16"),
            ("missing", vec![2, 2], "F32"),
        ] {
            let bad = BTreeMap::from([(
                name.into(),
                TensorSpec {
                    shape,
                    dtype: dtype.into(),
                },
            )]);
            assert!(validate_tensor_file(&path, &bad).is_err());
        }
        assert!(validate_tensor_file(&path, &BTreeMap::new()).is_err());
        Ok(())
    }
}
