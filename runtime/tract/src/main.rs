//! Development-only, bounded by the caller's process deadline.
use anyhow::ensure;
use std::{env, fs, time::Instant};
use tract_onnx::prelude::*;

fn stage(name: &str, started: Instant) {
    eprintln!(
        "{}",
        serde_json::json!({"stage": name, "elapsed_seconds": started.elapsed().as_secs_f64()})
    );
}

fn main() {
    if let Err(error) = probe() {
        eprintln!(
            "{}",
            serde_json::json!({"status": "failed", "error": format!("{error:#}")})
        );
        std::process::exit(1);
    }
}

fn probe() -> TractResult<()> {
    let args: Vec<_> = env::args().skip(1).collect();
    ensure!(
        args.len() >= 2 && args.len() <= 3,
        "usage: kaze_judge_tract_probe <model.onnx> <import|analyze|type|optimize|run> [inputs.json]"
    );
    let stop = &args[1];
    ensure!(
        ["import", "analyze", "type", "optimize", "run"].contains(&stop.as_str()),
        "invalid stage"
    );
    ensure!(
        (stop == "run") == (args.len() == 3),
        "run requires inputs.json; other stages take no input file"
    );
    let started = Instant::now();
    stage("load_started", started);
    let mut model = tract_onnx::onnx().model_for_path(&args[0])?;
    stage("imported", started);
    if stop == "analyze" {
        let _typed = model.into_typed()?;
        stage("typed", started);
        println!(
            "{}",
            serde_json::json!({"status": "completed", "last_stage": stop, "forward_executed": false})
        );
        return Ok(());
    }
    let mut logits = None;
    if stop != "import" {
        ensure!(
            model.input_outlets()?.len() == 3,
            "expected three Jeff inputs"
        );
        let names: Vec<String> = model
            .input_outlets()?
            .iter()
            .map(|outlet| model.node(outlet.node).name.clone())
            .collect();
        let mut sorted = names.clone();
        sorted.sort();
        ensure!(
            sorted == ["attention_mask", "input_ids", "mm_token_type_ids"],
            "unexpected Jeff input names: {names:?}"
        );
        for index in 0..model.input_outlets()?.len() {
            model.set_input_fact(index, i64::fact([1, 512]).into())?;
        }
        let typed = model.into_typed()?;
        stage("typed", started);
        if stop == "optimize" || stop == "run" {
            let optimized = typed.into_optimized()?;
            stage("optimized", started);
            if stop == "run" {
                let inputs: std::collections::BTreeMap<String, Vec<i64>> =
                    serde_json::from_slice(&fs::read(&args[2])?)?;
                ensure!(inputs.len() == 3, "expected exactly three inputs");
                let tensors: TVec<TValue> = names
                    .iter()
                    .map(|name| -> TractResult<TValue> {
                        let values = inputs
                            .get(name)
                            .ok_or_else(|| anyhow::anyhow!("missing {name}"))?;
                        ensure!(
                            values.len() == 512,
                            "{name} must contain exactly 512 i64 values"
                        );
                        Ok(
                            tract_ndarray::Array2::from_shape_vec((1, 512), values.clone())?
                                .into_tensor()
                                .into_tvalue(),
                        )
                    })
                    .collect::<TractResult<_>>()?;
                let plan = optimized.into_runnable()?;
                stage("runnable", started);
                let outputs = plan.run(tensors)?;
                ensure!(
                    outputs.len() == 1 && outputs[0].shape() == [1, 255],
                    "expected [1,255] logits"
                );
                let values = outputs[0]
                    .to_plain_array_view::<f32>()?
                    .iter()
                    .copied()
                    .collect::<Vec<_>>();
                ensure!(values.iter().all(|v| v.is_finite()), "nonfinite logits");
                logits = Some(values);
                stage("forward_completed", started);
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({"status": "completed", "last_stage": stop, "elapsed_seconds": started.elapsed().as_secs_f64(), "forward_executed": logits.is_some(), "raw_logits": logits})
    );
    Ok(())
}
