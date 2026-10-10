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

fn optimize_without_change_axes(mut model: TypedModel) -> TractResult<TypedModel> {
    let mut optimizer = tract_onnx::tract_core::optim::Optimizer::declutter();
    let before = optimizer.passes.len();
    optimizer
        .passes
        .retain(|pass| format!("{pass:?}") != "ChangeAxes");
    ensure!(
        optimizer.passes.len() + 1 == before,
        "expected exactly one ChangeAxes pass in pinned Tract"
    );
    optimizer.optimize(&mut model)?;
    model.optimize()?;
    Ok(model)
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
        "usage: kaze_judge_tract_probe <model.onnx> <import|analyze|type|optimize|run|run-typed|run-no-change-axes> [inputs.json]"
    );
    let stop = &args[1];
    ensure!(
        [
            "import",
            "analyze",
            "type",
            "optimize",
            "run",
            "run-typed",
            "run-no-change-axes"
        ]
        .contains(&stop.as_str()),
        "invalid stage"
    );
    ensure!(
        stop.starts_with("run") == (args.len() == 3),
        "run requires inputs.json; other stages take no input file"
    );
    let started = Instant::now();
    stage("load_started", started);
    let mut model = tract_onnx::onnx().model_for_path(&args[0])?;
    stage("imported", started);
    if stop == "analyze" {
        // The importer clears I64 facts in value_info, including duplicate inputs.
        // Restore only declared input types; keep the imported shapes intact.
        let proto = tract_onnx::onnx().proto_model_for_path(&args[0])?;
        let graph = proto
            .graph
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("missing graph"))?;
        let outlets = model.input_outlets()?.to_vec();
        for (index, outlet) in outlets.iter().enumerate() {
            let name = &model.node(outlet.node).name;
            if let Some(input) = graph.input.iter().find(|input| &input.name == name)
                && let Some(tract_onnx::pb::type_proto::Value::TensorType(tensor)) =
                    input.r#type.as_ref().and_then(|ty| ty.value.as_ref())
            {
                let dt: DatumType =
                    tract_onnx::pb::tensor_proto::DataType::try_from(tensor.elem_type)?
                        .try_into()?;
                let fact = model.input_fact(index)?.clone().with_datum_type(dt);
                model.set_input_fact(index, fact)?;
            }
        }
        if model.nodes().len() <= 100
            && let Err(error) = model.analyse(false)
        {
            for node in model.nodes() {
                eprintln!("{}: {:?}", node.name, node.outputs);
            }
            return Err(error);
        }
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
        if stop == "optimize" || stop.starts_with("run") {
            let optimized = if stop == "run-typed" {
                typed
            } else if stop == "run-no-change-axes" {
                let optimized = optimize_without_change_axes(typed)?;
                stage("optimized_without_change_axes", started);
                optimized
            } else {
                let optimized = typed.into_optimized()?;
                stage("optimized", started);
                optimized
            };
            if stop.starts_with("run") {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn integer_dimensions_preserve_i64_bounds() -> TractResult<()> {
        let values = [i64::MIN, -(1_i64 << 40), -1, 0, 1, 1_i64 << 40, i64::MAX];
        let input = tensor1(&values);
        let dimensions = input.cast_to::<TDim>()?;
        let actual = dimensions.to_plain_array_view::<TDim>()?;
        for (value, expected) in actual.iter().zip(values) {
            assert_eq!(value.to_i64()?, expected);
        }
        Ok(())
    }
}
