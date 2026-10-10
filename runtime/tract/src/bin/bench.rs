//! Development-only resident engine benchmark; no DecisionProvider contract.
use anyhow::ensure;
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs, io::Write, time::Instant};
use tract_onnx::prelude::*;

fn emit(value: Value) -> TractResult<()> {
    println!("{value}");
    std::io::stdout().flush()?;
    Ok(())
}

fn main() -> TractResult<()> {
    let started = Instant::now();
    let args: Vec<_> = std::env::args().skip(1).collect();
    ensure!(args.len() == 2, "usage: bench model.onnx job.json");
    let job: Value = serde_json::from_slice(&fs::read(&args[1])?)?;
    let mode = job["mode"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("missing mode"))?;
    ensure!(
        ["typed", "no-change-axes", "nnef-decluttered"].contains(&mode),
        "invalid mode"
    );
    tract_onnx::tract_core::tract_linalg::multithread::set_default_executor(
        tract_onnx::tract_core::tract_linalg::multithread::Executor::SingleThread,
    );
    let step = Instant::now();
    let (mut typed, load_ns, type_ns) = if mode == "nnef-decluttered" {
        let typed = tract_nnef::nnef().with_onnx().model_for_path(&args[0])?;
        (typed, step.elapsed().as_nanos(), 0)
    } else {
        let mut model = tract_onnx::onnx().model_for_path(&args[0])?;
        let load_ns = step.elapsed().as_nanos();
        for index in 0..3 {
            model.set_input_fact(index, i64::fact([1, 512]).into())?;
        }
        let step = Instant::now();
        let typed = model.into_typed()?;
        (typed, load_ns, step.elapsed().as_nanos())
    };
    let names: Vec<_> = typed
        .input_outlets()?
        .iter()
        .map(|outlet| typed.node(outlet.node).name.clone())
        .collect();
    for index in 0..3 {
        ensure!(
            typed.input_fact(index)? == &i64::fact([1, 512]),
            "invalid input fact"
        );
    }
    let mut sorted = names.clone();
    sorted.sort();
    ensure!(
        sorted == ["attention_mask", "input_ids", "mm_token_type_ids"],
        "invalid inputs"
    );
    let step = Instant::now();
    if mode == "no-change-axes" {
        let mut optimizer = tract_onnx::tract_core::optim::Optimizer::declutter();
        let before = optimizer.passes.len();
        optimizer
            .passes
            .retain(|pass| format!("{pass:?}") != "ChangeAxes");
        ensure!(
            optimizer.passes.len() + 1 == before,
            "pinned pass layout changed"
        );
        optimizer.optimize(&mut typed)?;
    }
    if ["no-change-axes", "nnef-decluttered"].contains(&mode) {
        typed.optimize()?;
    }
    let optimize_ns = step.elapsed().as_nanos();
    let step = Instant::now();
    let plan = typed.into_runnable()?;
    let plan_ns = step.elapsed().as_nanos();
    emit(
        json!({"event":"initialized", "backend":"tract", "mode":mode,
        "load_ns":load_ns,"type_ns":type_ns,"optimize_ns":optimize_ns,"plan_ns":plan_ns,
        "startup_ns":started.elapsed().as_nanos(),"threads":1,
        "asset_hash_verification":"parent preflight; excluded from child startup"}),
    )?;
    let cases = job["cases"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing cases"))?;
    for (iteration, item) in job["schedule"]
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("missing schedule"))?
        .iter()
        .enumerate()
    {
        let request_started = Instant::now();
        let index = item["case"]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("invalid case index"))? as usize;
        let case = cases
            .get(index)
            .ok_or_else(|| anyhow::anyhow!("case out of range"))?;
        let count = case["count"]
            .as_u64()
            .ok_or_else(|| anyhow::anyhow!("invalid count"))? as usize;
        let temperature = case["temperature"]
            .as_f64()
            .ok_or_else(|| anyhow::anyhow!("invalid temperature"))?
            as f32;
        ensure!(
            (2..=255).contains(&count) && temperature.is_finite() && temperature > 0.,
            "invalid scoring config"
        );
        let step = Instant::now();
        let inputs: BTreeMap<String, Vec<i64>> = serde_json::from_value(case["inputs"].clone())?;
        ensure!(inputs.len() == 3, "expected three inputs");
        let tensors: TVec<TValue> = names
            .iter()
            .map(|name| -> TractResult<TValue> {
                let values = inputs
                    .get(name)
                    .ok_or_else(|| anyhow::anyhow!("missing input"))?;
                ensure!(values.len() == 512, "expected 512 tokens");
                Ok(
                    tract_ndarray::Array2::from_shape_vec((1, 512), values.clone())?
                        .into_tensor()
                        .into_tvalue(),
                )
            })
            .collect::<TractResult<_>>()?;
        let prepare_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        // SimplePlan::run constructs fresh execution state for each request.
        let output = plan.run(tensors)?;
        ensure!(
            output.len() == 1 && output[0].shape() == [1, 255],
            "invalid output"
        );
        let raw: Vec<f32> = output[0]
            .to_plain_array_view::<f32>()?
            .iter()
            .copied()
            .collect();
        ensure!(raw.iter().all(|v| v.is_finite()), "nonfinite logits");
        let forward_ns = step.elapsed().as_nanos();
        let step = Instant::now();
        let masked: Vec<f32> = raw
            .iter()
            .enumerate()
            .map(|(i, v)| {
                if i < count {
                    *v / temperature
                } else {
                    -1e9 / temperature
                }
            })
            .collect();
        let maximum = masked.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let exp: Vec<f32> = masked.iter().map(|v| (*v - maximum).exp()).collect();
        let sum: f32 = exp.iter().sum();
        let probabilities: Vec<f32> = exp[..count].iter().map(|v| v / sum).collect();
        let score_ns = step.elapsed().as_nanos();
        emit(
            json!({"event":"request","case":case["id"],"iteration":iteration,"warmup":item["warmup"],
            "effective_tokens":case["tokens"],"physical_tokens":512,"prepare_ns":prepare_ns,
            "forward_ns":forward_ns,"score_ns":score_ns,"request_ns":request_started.elapsed().as_nanos(),
            "raw_logits":raw,"probabilities":probabilities}),
        )?;
    }
    emit(json!({"event":"completed","total_ns":started.elapsed().as_nanos()}))?;
    Ok(())
}
