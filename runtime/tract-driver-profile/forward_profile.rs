//! Public eval callback diagnostic. Child plans are included in their parent op.
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Instant};
use tract_onnx::{prelude::*, tract_core::model::TypedSimplePlan};

pub fn run(
    plan: &Arc<TypedSimplePlan>,
    inputs: TVec<TValue>,
) -> TractResult<(TVec<TValue>, Value)> {
    let started = Instant::now();
    let mut rows = Vec::new();
    let output = plan
        .spawn()?
        .run_plan_with_eval(inputs, |ctx, state, node, inputs| {
            let step = Instant::now();
            let output = tract_onnx::tract_core::plan::eval(ctx, state, node, inputs)?;
            let elapsed = step.elapsed().as_nanos();
            rows.push((
                node.id,
                node.name.clone(),
                node.op().name().to_string(),
                elapsed,
            ));
            Ok::<_, anyhow::Error>(output)
        })?;
    let total_ns = started.elapsed().as_nanos();
    let node_ns: u128 = rows.iter().map(|r| r.3).sum();
    let mut groups: BTreeMap<String, (usize, u128)> = BTreeMap::new();
    for row in &rows {
        let group = groups.entry(row.2.clone()).or_default();
        group.0 += 1;
        group.1 += row.3;
    }
    let mut groups: Vec<_> = groups.into_iter().collect();
    groups.sort_by_key(|(_, (_, ns))| std::cmp::Reverse(*ns));
    rows.sort_by_key(|r| std::cmp::Reverse(r.3));
    let profile = json!({"scope":"top-level eval wall time; child plans included; not CPU time",
        "total_ns":total_ns,"node_ns":node_ns,"driver_and_instrumentation_ns":total_ns-node_ns,
        "groups":groups.iter().map(|(op,(calls,ns))| json!({"op":op,"calls":calls,"ns":ns})).collect::<Vec<_>>(),
        "top_nodes":rows.iter().take(30).map(|(id,name,op,ns)| json!({"id":id,"name":name,"op":op,"ns":ns})).collect::<Vec<_>>()});
    Ok((output, profile))
}
