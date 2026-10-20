//! Diagnostic (#18): where full attention in query blocks stops being bitwise equal to one block
//! on a host, and what that does to the final hidden state, the probabilities and the judgment.
//!
//!   attention_block_diff synthetic
//!   attention_block_diff model <manifest> <request.json>...
//!
//! `synthetic` repeats the shapes and data of the library test
//! `attention_in_query_blocks_is_bitwise_equal_to_one_block` (plus 513 and 1024 rows in blocks of
//! 512, as in the forward), with the three stages of `backbone::attention_rows` (scores, softmax,
//! value product) compared row by row, and then a sweep of plain matmuls: row 0 of an m-row
//! product against the same row computed alone. `model` runs the forward with blocks of 512 and
//! as one block in the same process. One JSON line per result.
use anyhow::{Context, Result};
use candle_core::{Device, Tensor};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    readout,
    tokenize::Tokenizer,
    DecisionRequest, Limits,
};
use serde_json::json;
use std::{
    path::Path,
    time::{Duration, Instant},
};

// The generator of the library tests (xorshift, 24-bit mantissa).
fn uniform(seed: &mut u64, n: usize, low: f32, high: f32) -> Vec<f32> {
    (0..n)
        .map(|_| {
            *seed ^= *seed << 13;
            *seed ^= *seed >> 7;
            *seed ^= *seed << 17;
            low + (high - low) * ((*seed >> 40) as f32 / (1u64 << 24) as f32)
        })
        .collect()
}

fn values(t: &Tensor) -> Result<Vec<f32>> {
    Ok(t.flatten_all()?.to_vec1::<f32>()?)
}

/// The stages of `backbone::attention_rows` (same operations, same order).
fn stages(q: &Tensor, kt: &Tensor, v: &Tensor, start: usize, rows: usize) -> Result<[Tensor; 3]> {
    let seq = kt.dim(2)?;
    let q = if rows == q.dim(1)? {
        q.clone()
    } else {
        q.narrow(1, start, rows)?.contiguous()?
    };
    let scores = (q.matmul(kt)? / 16.0)?;
    let mask: Vec<f32> = (start..start + rows)
        .flat_map(|i| (0..seq).map(move |j| if j > i { f32::NEG_INFINITY } else { 0.0 }))
        .collect();
    let mask = Tensor::from_vec(mask, (1, rows, seq), &Device::Cpu)?;
    let probs = candle_nn::ops::softmax_last_dim(&scores.broadcast_add(&mask)?)?;
    let out = probs.matmul(v)?;
    Ok([scores, probs, out])
}

/// Bitwise-different elements, the largest absolute and relative difference (finite pairs).
fn compare(a: &[f32], b: &[f32]) -> (usize, f64, f64) {
    let a: Vec<_> = a.iter().map(|&x| (x.to_bits() as u64, x as f64)).collect();
    let b: Vec<_> = b.iter().map(|&x| (x.to_bits() as u64, x as f64)).collect();
    compare_bits(&a, &b)
}

fn compare64(a: &[f64], b: &[f64]) -> (usize, f64, f64) {
    let a: Vec<_> = a.iter().map(|&x| (x.to_bits(), x)).collect();
    let b: Vec<_> = b.iter().map(|&x| (x.to_bits(), x)).collect();
    compare_bits(&a, &b)
}

fn compare_bits(a: &[(u64, f64)], b: &[(u64, f64)]) -> (usize, f64, f64) {
    let (mut differ, mut abs, mut rel) = (0, 0f64, 0f64);
    for (&(xb, x), &(yb, y)) in a.iter().zip(b) {
        if xb != yb {
            differ += 1;
            if x.is_finite() && y.is_finite() {
                let d = (x - y).abs();
                abs = abs.max(d);
                let scale = x.abs().max(y.abs());
                if scale > 0.0 {
                    rel = rel.max(d / scale);
                }
            }
        }
    }
    (differ, abs, rel)
}

fn synthetic() -> Result<()> {
    let names = ["scores", "probs", "out"];
    let mut seed = 0x5eed_u64;
    let mut cases: Vec<(usize, Vec<usize>)> = [1, 7, 8, 9, 37].map(|s| (s, vec![1, 3, 8])).to_vec();
    cases.extend([(513, vec![512]), (1024, vec![512])]);
    for (seq, blocks) in cases {
        let q = Tensor::from_vec(
            uniform(&mut seed, 8 * seq * 256, -1.0, 1.0),
            (8, seq, 256),
            &Device::Cpu,
        )?;
        let kt = Tensor::from_vec(
            uniform(&mut seed, 8 * 256 * seq, -1.0, 1.0),
            (8, 256, seq),
            &Device::Cpu,
        )?;
        let v = Tensor::from_vec(
            uniform(&mut seed, 8 * seq * 256, -1.0, 1.0),
            (8, seq, 256),
            &Device::Cpu,
        )?;
        let whole = stages(&q, &kt, &v, 0, seq)?;
        for block in blocks {
            let mut parts: [Vec<Tensor>; 3] = Default::default();
            for start in (0..seq).step_by(block) {
                let rows = block.min(seq - start);
                for (part, t) in parts.iter_mut().zip(stages(&q, &kt, &v, start, rows)?) {
                    part.push(t);
                }
            }
            let mut report = serde_json::Map::new();
            for ((name, part), whole) in names.iter().zip(&parts).zip(&whole) {
                let (differ, abs, rel) = compare(&values(&Tensor::cat(part, 1)?)?, &values(whole)?);
                report.insert(
                    name.to_string(),
                    json!({"differ": differ, "max_abs": abs, "max_rel": rel}),
                );
            }
            // The value product of the blocked probabilities taken from one block: isolates the
            // second matmul from a difference already present in the probabilities.
            let mut out_from_whole_probs = Vec::new();
            for start in (0..seq).step_by(block) {
                let rows = block.min(seq - start);
                out_from_whole_probs
                    .push(whole[1].narrow(1, start, rows)?.contiguous()?.matmul(&v)?);
            }
            let (differ, abs, rel) = compare(
                &values(&Tensor::cat(&out_from_whole_probs, 1)?)?,
                &values(&whole[2])?,
            );
            report.insert(
                "out_given_equal_probs".into(),
                json!({"differ": differ, "max_abs": abs, "max_rel": rel}),
            );
            println!(
                "{}",
                json!({"kind": "attention", "seq": seq, "block": block, "elements": 8 * seq * 256, "stages": report})
            );
        }
    }
    // Plain matmuls: is row 0 of an (m x k)(k x n) product the same as row 0 computed alone?
    for &(k, n) in &[
        (256, 7),
        (256, 37),
        (256, 513),
        (7, 256),
        (37, 256),
        (513, 256),
        (1024, 256),
    ] {
        let mut same = Vec::new();
        let mut differ = Vec::new();
        let rhs = Tensor::from_vec(uniform(&mut seed, k * n, -1.0, 1.0), (k, n), &Device::Cpu)?;
        let lhs_all = Tensor::from_vec(
            uniform(&mut seed, 512 * k, -1.0, 1.0),
            (512, k),
            &Device::Cpu,
        )?;
        let alone = values(&lhs_all.narrow(0, 0, 1)?.contiguous()?.matmul(&rhs)?)?;
        for m in [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 32, 37, 64, 65, 128, 512] {
            let product = values(&lhs_all.narrow(0, 0, m)?.contiguous()?.matmul(&rhs)?)?;
            if compare(&product[..n], &alone).0 == 0 {
                same.push(m)
            } else {
                differ.push(m)
            }
        }
        println!(
            "{}",
            json!({"kind": "matmul_row0", "k": k, "n": n, "rows_equal_to_alone": same, "rows_differing": differ})
        );
    }
    Ok(())
}

#[derive(serde::Deserialize)]
struct Wrapped {
    request: DecisionRequest,
}

fn model(manifest: &str, paths: &[String]) -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    pure_jeff::configure_threads(header.policy.cpu_threads)?;
    let bundle = Bundle::verify(Path::new(manifest), deadline, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    // SAFETY: as above.
    let readout_weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("readout.safetensors"))?
    };
    for path in paths {
        let text = std::fs::read_to_string(path)?;
        let request = serde_json::from_str::<Wrapped>(&text)
            .map(|w| w.request)
            .or_else(|_| serde_json::from_str::<DecisionRequest>(&text))
            .with_context(|| path.clone())?;
        let limits = Limits {
            max_input_bytes: 1024 * 1024,
            max_input_tokens: 8192,
            max_forwards: 1,
            deadline,
        };
        let ids = tokenizer.prepare(&bundle.decision, &request, limits)?.ids;
        let mut hidden = Vec::new();
        let mut probabilities = Vec::new();
        let mut judgments = Vec::new();
        for block in [backbone::QUERY_BLOCK, usize::MAX] {
            let h = backbone::forward_blocks(&weights, &ids, &|| Ok(()), true, block)?;
            let p = readout::probabilities(
                &readout_weights,
                &h,
                request.candidates.len(),
                bundle.decision.temperature,
            )?;
            judgments.push(format!("{:?}", bundle.manifest.policy.judge(&request, &p)?));
            hidden.push(values(&h)?);
            probabilities.push(p);
        }
        let (h_differ, h_abs, h_rel) = compare(&hidden[0], &hidden[1]);
        let (p_differ, p_abs, p_rel) = compare64(&probabilities[0], &probabilities[1]);
        println!(
            "{}",
            json!({"kind": "model", "request": path, "tokens": ids.len(),
            "hidden": {"differ": h_differ, "elements": hidden[0].len(), "max_abs": h_abs, "max_rel": h_rel},
            "probabilities": {"differ": p_differ, "max_abs": p_abs, "max_rel": p_rel,
                              "blocked": probabilities[0], "one_block": probabilities[1]},
            "judgment_equal": judgments[0] == judgments[1]})
        );
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("synthetic") => synthetic(),
        Some("model") if args.len() >= 3 => model(&args[1], &args[2..]),
        _ => anyhow::bail!(
            "usage: attention_block_diff synthetic | model <manifest> <request.json>..."
        ),
    }
}
