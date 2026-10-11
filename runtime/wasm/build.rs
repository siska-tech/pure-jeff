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
const SLICE_COPIES: [(&str, &str, Substitutions); 3] = [
    // Native diagnostic copy with timers (crate::profile); the arithmetic is unchanged and the
    // profile example checks that its output is bitwise equal to the frozen forward.
    (
        "backbone_profiled.rs",
        "backbone.rs",
        &[
            (
                "    weights.load(name, &Device::Cpu)?.to_dtype(DType::F32)\n}",
                "    let t = std::time::Instant::now();\n    let loaded = weights.load(name, &Device::Cpu)?;\n    crate::profile::add(crate::profile::LOAD, t);\n    let t = std::time::Instant::now();\n    let converted = loaded.to_dtype(DType::F32);\n    crate::profile::add(crate::profile::CONVERT, t);\n    converted\n}",
            ),
            (
                "    x.matmul(&weight(weights, &format!(\"{name}.weight\"))?.t()?)\n}",
                "    let w = weight(weights, &format!(\"{name}.weight\"))?;\n    let t = std::time::Instant::now();\n    let out = x.matmul(&w.t()?);\n    crate::profile::add(crate::profile::MATMUL, t);\n    out\n}",
            ),
            (
                "    let embedding = weights.load(\"language_model.embed_tokens.weight\", &Device::Cpu)?;",
                "    let t = std::time::Instant::now();\n    let embedding = weights.load(\"language_model.embed_tokens.weight\", &Device::Cpu)?;\n    crate::profile::add(crate::profile::EMBED, t);",
            ),
            ("fn mlp(x: &Tensor", "fn mlp_untimed(x: &Tensor"),
            ("fn full_attention(x: &Tensor", "fn full_attention_untimed(x: &Tensor"),
            ("fn linear_attention(x: &Tensor", "fn linear_attention_untimed(x: &Tensor"),
            ("fn delta_recurrence(\n", "fn delta_recurrence_untimed(\n"),
            (
                "#[cfg(test)]\nmod tests {",
                "fn mlp(x: &Tensor, weights: &MmapedSafetensors, prefix: &str) -> Result<Tensor> {\n    let t = std::time::Instant::now();\n    let out = mlp_untimed(x, weights, prefix);\n    crate::profile::add(crate::profile::MLP, t);\n    out\n}\n\nfn full_attention(x: &Tensor, weights: &MmapedSafetensors, prefix: &str) -> Result<Tensor> {\n    let t = std::time::Instant::now();\n    let out = full_attention_untimed(x, weights, prefix);\n    crate::profile::add(crate::profile::FULL_ATTENTION, t);\n    out\n}\n\nfn linear_attention(x: &Tensor, weights: &MmapedSafetensors, prefix: &str) -> Result<Tensor> {\n    let t = std::time::Instant::now();\n    let out = linear_attention_untimed(x, weights, prefix);\n    crate::profile::add(crate::profile::LINEAR_ATTENTION, t);\n    out\n}\n\nfn delta_recurrence(q: &Tensor, k: &Tensor, v: &Tensor, beta: &Tensor, g: &Tensor) -> Result<Tensor> {\n    let t = std::time::Instant::now();\n    let out = delta_recurrence_untimed(q, k, v, beta, g);\n    crate::profile::add(crate::profile::DELTA, t);\n    out\n}\n\n#[cfg(test)]\nmod tests {",
            ),
        ],
    ),
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
