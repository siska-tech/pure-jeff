//! Exercise actual Graph and ModelPatch naming, with one renamed node per patch.
use tract_onnx::prelude::*;
use tract_onnx::tract_core::{model::TypedModelPatch, ops::identity::Identity};

fn main() -> TractResult<()> {
    for (names, prefix, expected) in [
        (vec!["a", "a.1", "a.3"], "a", "a.2"),
        (vec!["a", "a.01", "a.+1", "a.0"], "a", "a.1"),
        (vec!["a.1"], "a", "a"),
        (vec!["", ".1"], "", ".2"),
        (vec!["日本", "日本.1"], "日本", "日本.2"),
        (vec!["a", "a", "a.1"], "a", "a.2"),
    ] {
        let mut model = TypedModel::default();
        for name in names {
            model.add_source(name, f32::fact([2]))?;
        }
        anyhow::ensure!(model.unique_name(prefix) == expected);
    }
    for (new_name, existing, expected, garbage) in [
        ("a", vec!["a", "a.1", "a.3"], "a.2", false),
        ("a#tail", vec!["a", "a.1", "a.3"], "a.2", false),
        ("a#tail#again", vec!["a.1"], "a", false),
        ("日本#1", vec!["日本", "日本.1"], "日本.2", false),
        ("a", vec![], "a", true),
    ] {
        let mut model = TypedModel::default();
        let input = model.add_source("input", f32::fact([2]))?;
        for name in existing {
            model.wire_node(name, Identity, &[input])?;
        }
        let old = model.wire_node(if garbage { "a" } else { "old" }, Identity, &[input])?[0];
        model.select_output_outlets(&[old])?;
        let mut patch = TypedModelPatch::default();
        let tap = patch.tap_model(&model, input)?;
        let new = patch.wire_node(new_name, Identity, &[tap])?[0];
        patch.shunt_outside(&model, old, new)?;
        patch.apply(&mut model)?;
        model.check_edges()?;
        let output = model.output_outlets()?[0];
        anyhow::ensure!(model.node(output.node).name == expected);
        let result = model
            .into_runnable()?
            .run(tvec!(tensor1(&[2f32, 5.]).into()))?;
        anyhow::ensure!(
            result[0]
                .to_plain_array_view::<f32>()?
                .iter()
                .copied()
                .collect::<Vec<_>>()
                == [2., 5.]
        );
    }
    println!("name semantics: 6 Graph cases and 5 patch cases passed");
    Ok(())
}
