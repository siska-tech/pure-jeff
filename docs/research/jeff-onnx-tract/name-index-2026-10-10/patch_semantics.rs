//! Small valid graph regressions for the isolated ModelPatch experiment.
use serde_json::json;
use tract_onnx::prelude::*;
use tract_onnx::tract_core::{model::TypedModelPatch, ops::identity::Identity};

fn main() -> TractResult<()> {
    for constants in [false, true] {
        let mut model = TypedModel::default();
        let input = model.add_source("input", f32::fact([2]))?;
        let existing = model.wire_node("existing", Identity, &[input])?[0];
        let old = model.wire_node("old", Identity, &[input])?[0];
        model.select_output_outlets(&[old, existing])?;
        model.set_outlet_label(old, "result".into())?;
        let mut patch = TypedModelPatch::default();
        let tap = patch.tap_model(&model, input)?;
        let first = patch.wire_node("replacement", Identity, &[tap])?[0];
        let second = patch.wire_node("second", Identity, &[first])?[0];
        if constants {
            let value = tensor1(&[3f32, 7.]);
            let a = model.add_const("shared", value.clone())?;
            let b = patch.add_const("shared", value)?;
            let replacement = patch.wire_node("constant-copy", Identity, &[b])?[0];
            // Shared constant values in target and patch, two shunted model outputs.
            model.select_output_outlets(&[old, existing, a])?;
            patch.shunt_outside(&model, a, replacement)?;
        }
        patch.shunt_outside(&model, old, second)?;
        patch.apply(&mut model)?;
        model.check_edges()?;
        let nodes: Vec<_> = model
            .nodes()
            .iter()
            .map(|n| {
                json!({
                    "id": n.id, "name": n.name, "op": n.op().name(),
                    "inputs": n.inputs.iter().map(|o| (o.node,o.slot)).collect::<Vec<_>>(),
                    "outputs": n.outputs.len(),
                })
            })
            .collect();
        let outputs: Vec<_> = model
            .output_outlets()?
            .iter()
            .map(|o| (o.node, o.slot))
            .collect();
        let labels: Vec<_> = model
            .output_outlets()?
            .iter()
            .map(|o| model.outlet_label(*o))
            .collect();
        let result = model
            .clone()
            .into_runnable()?
            .run(tvec!(tensor1(&[2f32, 5.]).into()))?;
        let values: Vec<Vec<f32>> = result
            .iter()
            .map(|v| Ok(v.to_plain_array_view::<f32>()?.iter().copied().collect()))
            .collect::<TractResult<_>>()?;
        anyhow::ensure!(values[0] == [2., 5.] && values[1] == [2., 5.]);
        if constants {
            anyhow::ensure!(values[2] == [3., 7.]);
        }
        println!(
            "{}",
            json!({"constants":constants,"nodes":nodes,"outputs":outputs,"labels":labels,"values":values})
        );
    }
    // A single operator with two output slots, both remapped by the same patch.
    let mut model = TypedModel::default();
    let input = model.add_source("input", f32::fact([2]))?;
    let k = model.add_const("k", tensor0(1i64))?;
    let op = tract_onnx::tract_core::ops::array::Topk {
        axis: 0,
        largest: true,
        fallback_k: 1.into(),
    };
    let existing = model.wire_node("existing", op.clone(), &[input, k])?;
    let old = model.wire_node("old", op.clone(), &[input, k])?;
    model.select_output_outlets(&[old[0], old[1], existing[0], existing[1]])?;
    let mut patch = TypedModelPatch::default();
    let taps = patch.taps(&model, &[input, k])?;
    let new = patch.wire_node("replacement", op, &taps)?;
    for slot in 0..2 {
        patch.shunt_outside(&model, old[slot], new[slot])?;
    }
    patch.apply(&mut model)?;
    model.check_edges()?;
    let nodes: Vec<_> = model
        .nodes()
        .iter()
        .map(|n| {
            json!({
                "id":n.id,"name":n.name,"op":n.op().name(),"outputs":n.outputs.len(),
                "inputs":n.inputs.iter().map(|o| (o.node,o.slot)).collect::<Vec<_>>(),
            })
        })
        .collect();
    let outputs: Vec<_> = model
        .output_outlets()?
        .iter()
        .map(|o| (o.node, o.slot))
        .collect();
    let result = model
        .into_runnable()?
        .run(tvec!(tensor1(&[2f32, 5.]).into()))?;
    let values: Vec<Vec<f32>> = result
        .iter()
        .map(|v| {
            Ok(v.cast_to_dt(DatumType::F32)?
                .to_plain_array_view::<f32>()?
                .iter()
                .copied()
                .collect())
        })
        .collect::<TractResult<_>>()?;
    anyhow::ensure!(values == [vec![5.], vec![1.], vec![5.], vec![1.]]);
    println!(
        "{}",
        json!({"multi_output_node":true,"nodes":nodes,"outputs":outputs,"values":values})
    );
    Ok(())
}
