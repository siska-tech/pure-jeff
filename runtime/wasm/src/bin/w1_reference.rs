//! Native (x86_64) run of the same W1 decision code on the same files.
use std::{fs, path::Path};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [manifest, request, max_tokens, output] = args.as_slice() else {
        anyhow::bail!(
            "usage: w1_reference <manifest.json> <request.json> <max-input-tokens> <output.json>"
        );
    };
    anyhow::ensure!(!Path::new(output).exists(), "output already exists");
    let manifest_bytes = fs::read(manifest)?;
    let value: serde_json::Value = serde_json::from_slice(&manifest_bytes)?;
    let root = Path::new(manifest).parent().unwrap().join(
        value["checkpoint_dir"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("checkpoint_dir"))?,
    );
    let read = |name: &str| fs::read(root.join(name));
    let (config, tokenizer, readout, model) = (
        read("decision_config.json")?,
        read("tokenizer.json")?,
        read("readout.safetensors")?,
        read("model.safetensors")?,
    );
    let assets = kaze_judge_wasm_probe::decide::Assets {
        manifest: &manifest_bytes,
        decision_config: &config,
        tokenizer: &tokenizer,
        readout: &readout,
        model: &model,
    };
    let result =
        kaze_judge_wasm_probe::decide::decide(&assets, &fs::read(request)?, max_tokens.parse()?)?;
    fs::write(output, serde_json::to_vec(&result)?)?;
    Ok(())
}
