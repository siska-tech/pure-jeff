//! Experimental NNEF serialization feasibility probe; never overwrites an asset.
use anyhow::ensure;
use serde_json::json;
use std::{fs::OpenOptions, io::Write, time::Instant};
use tract_onnx::prelude::*;

fn emit(value: serde_json::Value) -> TractResult<()> {
    println!("{value}");
    std::io::stdout().flush()?;
    Ok(())
}

fn main() -> TractResult<()> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    ensure!(
        args.len() == 3,
        "usage: pack model.onnx output.nnef.tar optimized|decluttered"
    );
    ensure!(
        ["optimized", "decluttered"].contains(&args[2].as_str()),
        "invalid profile"
    );
    ensure!(
        !std::path::Path::new(&args[1]).exists(),
        "output already exists"
    );
    tract_onnx::tract_core::tract_linalg::multithread::set_default_executor(
        tract_onnx::tract_core::tract_linalg::multithread::Executor::SingleThread,
    );
    let started = Instant::now();
    let mut model = tract_onnx::onnx().model_for_path(&args[0])?;
    for index in 0..3 {
        model.set_input_fact(index, i64::fact([1, 512]).into())?;
    }
    let mut model = model.into_typed()?;
    emit(json!({"event":"typed", "elapsed_ns":started.elapsed().as_nanos()}))?;
    let mut optimizer = tract_onnx::tract_core::optim::Optimizer::declutter();
    let before = optimizer.passes.len();
    optimizer
        .passes
        .retain(|pass| format!("{pass:?}") != "ChangeAxes");
    ensure!(
        optimizer.passes.len() + 1 == before,
        "pinned pass layout changed"
    );
    optimizer.optimize(&mut model)?;
    if args[2] == "optimized" {
        model.optimize()?;
    }
    emit(
        json!({"event":"prepared", "profile":args[2], "elapsed_ns":started.elapsed().as_nanos()}),
    )?;
    let output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[1])?;
    let output = tract_nnef::nnef()
        .with_onnx()
        .write_to_tar_with_config(&model, output, false, true)?;
    output.sync_all()?;
    emit(json!({"event":"saved", "profile":args[2], "elapsed_ns":started.elapsed().as_nanos()}))?;
    Ok(())
}
