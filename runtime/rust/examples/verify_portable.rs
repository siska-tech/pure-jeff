//! Rust-only local package verification, requiring no Python or PowerShell scripts.
use anyhow::{ensure, Context, Result};
use kaze_judge::{evaluate, DecisionRequest, Judgment, Limits, NativeProcessProvider, Outcome};
use kaze_judge_jeff::bundle;
use serde::Deserialize;
use std::{
    collections::HashSet,
    fs,
    path::{Component, Path, PathBuf},
    time::{Duration, Instant},
};
#[derive(Deserialize)]
struct Index {
    schema_version: String,
    release_ready: bool,
    files: Vec<Record>,
    payload_bytes: u64,
}
#[derive(Deserialize)]
struct Record {
    path: String,
    bytes: u64,
    sha256: String,
}
#[derive(Deserialize)]
struct Expected {
    input_tokens: usize,
    judgment: Judgment,
    scores: Vec<kaze_judge::CandidateScore>,
}
fn plain(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path)?;
    ensure!(!m.file_type().is_symlink(), "symlink rejected");
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        ensure!(m.file_attributes() & 0x400 == 0, "reparse point rejected");
    }
    ensure!(m.is_file() || m.is_dir(), "unsupported file type");
    Ok(())
}
fn inventory(root: &Path, directory: &Path, found: &mut HashSet<String>) -> Result<()> {
    plain(directory)?;
    for entry in fs::read_dir(directory)? {
        let path = entry?.path();
        plain(&path)?;
        if path.is_dir() {
            inventory(root, &path, found)?;
        } else {
            let name = path
                .strip_prefix(root)?
                .to_str()
                .context("non UTF-8 path")?
                .replace('\\', "/");
            if name != "package.json" {
                ensure!(found.insert(name.to_lowercase()), "duplicate file");
            }
        }
    }
    Ok(())
}
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().collect();
    ensure!(args.len() <= 2, "usage: verify [package-directory]");
    let root = if let Some(root) = args.get(1) {
        PathBuf::from(root)
    } else {
        std::env::current_exe()?
            .parent()
            .context("executable parent")?
            .to_path_buf()
    };
    plain(&root)?;
    let root = root.canonicalize()?;
    let deadline = Instant::now() + Duration::from_secs(120);
    let index: Index = bundle::read_json(&root.join("package.json"), 4 * 1024 * 1024)?;
    ensure!(
        index.schema_version == "kaze_judge.portable.v1",
        "unsupported package schema"
    );
    let mut expected = HashSet::new();
    let mut payload_bytes = 0u64;
    for record in &index.files {
        let relative = Path::new(&record.path);
        ensure!(
            !record.path.is_empty()
                && relative
                    .components()
                    .all(|p| matches!(p, Component::Normal(_)))
                && !record.path.contains(':')
                && !record.path.contains('\\')
                && record.path != "package.json",
            "invalid inventory path"
        );
        ensure!(
            expected.insert(record.path.to_lowercase()),
            "duplicate inventory path"
        );
        let mut path = root.clone();
        for part in relative.components() {
            path.push(part);
            plain(&path)?;
        }
        ensure!(
            fs::metadata(&path)?.len() == record.bytes
                && bundle::hash_file(&path, deadline)? == record.sha256,
            "payload mismatch: {}",
            record.path
        );
        payload_bytes = payload_bytes
            .checked_add(record.bytes)
            .context("payload overflow")?;
    }
    let mut actual = HashSet::new();
    inventory(&root, &root, &mut actual)?;
    ensure!(
        expected == actual && payload_bytes == index.payload_bytes,
        "package file set mismatch"
    );
    let request: DecisionRequest =
        bundle::read_json(&root.join("smoke-request.json"), 1024 * 1024)?;
    let reference: Expected = bundle::read_json(&root.join("smoke-expected.json"), 1024 * 1024)?;
    let mut provider = NativeProcessProvider::new(root.join("jeff.exe"), root.join("bundle.json"))?;
    let attempt = evaluate(
        &mut provider,
        request,
        Limits {
            max_input_bytes: 1024 * 1024,
            max_input_tokens: 512,
            max_forwards: 1,
            deadline,
        },
    )?;
    let Outcome::Completed(observed) = attempt.outcome else {
        anyhow::bail!("package smoke failed: {:?}", attempt.outcome);
    };
    ensure!(
        attempt.provider_calls_started == 1
            && observed.judgment == reference.judgment
            && observed.input_tokens == reference.input_tokens
            && observed.forwards == 1
            && observed.scores.len() == reference.scores.len(),
        "smoke contract mismatch"
    );
    for (a, b) in observed.scores.iter().zip(&reference.scores) {
        ensure!(
            a.candidate_id == b.candidate_id
                && (a.option_probability - b.option_probability).abs() <= 1e-4,
            "smoke distribution mismatch"
        );
    }
    println!(
        "{}",
        serde_json::json!({"status":"verified_local_prototype","files":actual.len(),
        "input_tokens":observed.input_tokens,"judgment":observed.judgment,"release_ready":index.release_ready})
    );
    Ok(())
}
