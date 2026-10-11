//! Reuses the frozen Native sources; a changed source fails the build. The W1 copies differ
//! from the frozen files only by the listed weight-access substitutions.
use sha2::{Digest, Sha256};
use std::{env, fs, path::Path};

const FROZEN: [(&str, &str); 4] = [
    (
        "backbone.rs",
        "6e4f79c9e510a7da6b4b7fbbc16539343937ecd1887327d518f360b2c29bda1a",
    ),
    (
        "prompt.rs",
        "d8139cd0cb1b2c792ae887b86d52a26fc7573f07de4205cb75c8ad16a0ebbf6c",
    ),
    (
        "readout.rs",
        "90a2781c46f07ff76fde874fa0482de807b1815f13d53a609ee8235c9667b867",
    ),
    (
        "policy.rs",
        "7adee7fb4a679e79abc8ed0b86113ee333c60791dbe71d85a81ac85e96635a57",
    ),
];

/// Exact (from, to) substitutions; each `from` must occur exactly once.
type Substitutions = &'static [(&'static str, &'static str)];

/// (generated file, frozen source, substitutions)
const SLICE_COPIES: [(&str, &str, Substitutions); 2] = [
    (
        "backbone_slice.rs",
        "backbone.rs",
        &[(
            "safetensors::MmapedSafetensors,",
            "safetensors::SliceSafetensors as MmapedSafetensors,",
        )],
    ),
    (
        "readout_slice.rs",
        "readout.rs",
        &[
            (
                "safetensors::MmapedSafetensors,",
                "safetensors::SliceSafetensors,",
            ),
            ("use std::path::Path;\n", ""),
            ("    root: &Path,\n", "    readout: &[u8],\n"),
            (
                "    // SAFETY: caller verified the bundle and keeps its files immutable during inference.\n    let weights = unsafe { MmapedSafetensors::new(root.join(\"readout.safetensors\"))? };\n",
                "    let weights = SliceSafetensors::new(readout)?;\n",
            ),
        ],
    ),
];

fn includable(text: &str) -> String {
    // include! cannot take inner doc comments; only those lines are rewritten.
    let text = text.replace("\n//!", "\n//");
    text.strip_prefix("//!")
        .map_or(text.clone(), |rest| format!("//{rest}"))
}

fn main() {
    let out = Path::new(&env::var("OUT_DIR").unwrap()).to_path_buf();
    let mut sources = std::collections::HashMap::new();
    for (name, expected) in FROZEN {
        let path = Path::new("../rust/src").join(name);
        println!("cargo:rerun-if-changed={}", path.display());
        let bytes = fs::read(&path).unwrap();
        let actual = format!("{:x}", Sha256::digest(&bytes));
        assert_eq!(actual, expected, "frozen Native source changed: {name}");
        let text = String::from_utf8(bytes).unwrap();
        fs::write(out.join(name), includable(&text)).unwrap();
        sources.insert(name, text);
    }
    for (generated, source, substitutions) in SLICE_COPIES {
        let mut text = sources[source].clone();
        for (from, to) in substitutions {
            assert_eq!(text.matches(from).count(), 1, "{generated}: {from:?}");
            text = text.replace(from, to);
        }
        fs::write(out.join(generated), includable(&text)).unwrap();
    }
}
