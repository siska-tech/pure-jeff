//! Native (x86_64) W2 reference: one session, every case decided in order.
use std::{fs, path::Path};

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [manifest, cases, max_tokens, output] = args.as_slice() else {
        anyhow::bail!(
            "usage: w2_reference <manifest.json> <cases.json> <max-input-tokens> <output.json>"
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
    let assets = pure_jeff_wasm_probe::decide::Assets {
        manifest: &manifest_bytes,
        decision_config: &config,
        tokenizer: &tokenizer,
        readout: &readout,
        model: &model,
    };
    let (session, open_stages) = pure_jeff_wasm_probe::decide::Session::open(&assets)?;
    // cases.json: [{"name": ..., "request": <path relative to cases.json>}]
    let cases_path = Path::new(cases);
    let cases: Vec<serde_json::Value> = serde_json::from_slice(&fs::read(cases_path)?)?;
    let mut results = serde_json::Map::new();
    for case in cases {
        let name = case["name"].as_str().unwrap().to_owned();
        let request = fs::read(
            cases_path
                .parent()
                .unwrap()
                .join(case["request"].as_str().unwrap()),
        )?;
        results.insert(name, session.decide(&request, max_tokens.parse()?)?);
    }
    let out = serde_json::json!({"open_stages": open_stages, "results": results});
    fs::write(output, serde_json::to_vec(&out)?)?;
    Ok(())
}
