//! Diagnostic: the final hidden state is bitwise the same with every weight path, for every
//! request given, in an interleaved order (so a buffer reused by one request cannot leak into
//! the next):
//!   plain     every weight converted into new memory (`forward_checked_with(.., false)`)
//!   reused    weights of the same role converted into one buffer per forward (the Native default)
//!   retained  `LoadOptions::retain_f32` tensors, with and without reuse
//! Prints one JSON line per request and path; exits non-zero on any difference.
//!
//!   cargo run --release --example weights_check -- <manifest> <request-or-golden.json>...
use anyhow::{ensure, Context, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    tokenize::Tokenizer,
    DecisionRequest, Limits, LoadOptions, Model,
};
use std::{
    path::Path,
    time::{Duration, Instant},
};

#[derive(serde::Deserialize)]
struct Wrapped {
    request: DecisionRequest,
}

fn bits(t: &candle_core::Tensor) -> Result<Vec<u32>> {
    Ok(t.flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .map(|v| v.to_bits())
        .collect())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (manifest, paths) = args
        .split_first()
        .context("usage: weights_check <manifest> <request.json>...")?;
    let deadline = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    pure_jeff::configure_threads(header.policy.cpu_threads)?;
    let bundle = Bundle::verify(Path::new(manifest), deadline, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let mapped = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    // SAFETY: as above.
    let second = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    let mut names: Vec<String> = second
        .tensors()
        .into_iter()
        .map(|(n, _)| n)
        .filter(|n| n.starts_with("language_model.") && n != "language_model.embed_tokens.weight")
        .collect();
    names.sort();
    let retained =
        pure_jeff::Retained::new(second, names.iter().map(String::as_str), &mut || Ok(()))?;
    let model = Model::load(
        manifest,
        &LoadOptions {
            retain_f32: true,
            ..LoadOptions::default()
        },
    )?;
    ensure!(model.retained_f32_bytes() == 1_992_453_376 + 1_044_480);
    let mut requests = Vec::new();
    for path in paths {
        let text = std::fs::read_to_string(path)?;
        let request = serde_json::from_str::<Wrapped>(&text)
            .map(|w| w.request)
            .or_else(|_| serde_json::from_str::<DecisionRequest>(&text))?;
        let prepared = tokenizer.prepare(
            &bundle.decision,
            &request,
            Limits {
                max_input_bytes: 1024 * 1024,
                max_input_tokens: 8192,
                max_forwards: 1,
                deadline,
            },
        )?;
        requests.push((path.clone(), prepared.ids));
    }
    let never = || Ok(());
    let mut reference = Vec::new();
    for (_, ids) in &requests {
        reference.push(bits(&backbone::forward_checked_with(
            &mapped, ids, &never, false,
        )?)?);
    }
    let mut failed = false;
    // Each path visits the requests forwards then backwards, after all the others ran.
    for (path_name, source, reuse) in [
        ("reused", &mapped as &dyn pure_jeff::WeightSource, true),
        ("retained", &retained as &dyn pure_jeff::WeightSource, false),
        (
            "retained+reused",
            &retained as &dyn pure_jeff::WeightSource,
            true,
        ),
    ] {
        let order: Vec<usize> = (0..requests.len())
            .chain((0..requests.len()).rev())
            .collect();
        for i in order {
            let (name, ids) = &requests[i];
            let started = Instant::now();
            let hidden = bits(&backbone::forward_checked_with(source, ids, &never, reuse)?)?;
            let equal = hidden == reference[i];
            failed |= !equal;
            println!(
                "{}",
                serde_json::json!({"request": name, "tokens": ids.len(), "path": path_name,
                    "forward_s": started.elapsed().as_secs_f64(), "bitwise_equal": equal})
            );
        }
    }
    ensure!(!failed, "a weight path changed the hidden state");
    Ok(())
}
