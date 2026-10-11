//! Deterministic small operator fixtures. Inputs come from an integer generator, so the
//! native and wasm32 builds start from bit-identical f32 values.
use crate::{frozen, now_ms};
use anyhow::Result;
use candle_core::{Device, Tensor, D};
use serde_json::{json, Value};

struct Inputs(u64);
impl Inputs {
    fn values(&mut self, count: usize) -> Vec<f32> {
        (0..count)
            .map(|_| {
                self.0 = self
                    .0
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                // 24 random bits scaled to [-1, 1): exact in f32 on every target.
                ((self.0 >> 40) as f32 / (1u32 << 23) as f32) - 1.0
            })
            .collect()
    }
    fn tensor(&mut self, shape: &[usize]) -> Result<Tensor> {
        let count = shape.iter().product();
        Ok(Tensor::from_vec(self.values(count), shape, &Device::Cpu)?)
    }
}

fn record(name: &str, started: f64, out: &Tensor) -> Result<Value> {
    let elapsed = now_ms() - started;
    let values = out.flatten_all()?.to_vec1::<f32>()?;
    if values.iter().any(|v| !v.is_finite()) {
        anyhow::bail!("{name}: non-finite output");
    }
    Ok(json!({"name": name, "shape": out.dims(), "elapsed_ms": elapsed, "values": values}))
}

/// Same as the frozen `linear`: x · Wᵀ with W stored as (out, in).
fn linear(x: &Tensor, w: &Tensor) -> Result<Tensor> {
    Ok(x.matmul(&w.t()?)?)
}

pub fn run() -> Result<Value> {
    let mut gen = Inputs(0x4a45_4646_5730);
    let mut cases = Vec::new();

    // GEMM at model widths (hidden 1024, MLP 3584) with an odd sequence length.
    let x = gen.tensor(&[17, 1024])?;
    let w = gen.tensor(&[3584, 1024])?;
    let t = now_ms();
    let up = linear(&x, &w)?;
    cases.push(record("gemm_17x1024_by_3584x1024T", t, &up)?);

    let w = gen.tensor(&[1024, 3584])?;
    let t = now_ms();
    let down = linear(&up.silu()?, &w)?;
    cases.push(record("gemm_silu_17x3584_by_1024x3584T", t, &down)?);

    let x = gen.tensor(&[5, 64])?;
    let w = gen.tensor(&[33, 64])?;
    let t = now_ms();
    cases.push(record("gemm_odd_5x64_by_33x64T", t, &linear(&x, &w)?)?);

    // Batched attention-score shape: (heads, seq, dim) · (heads, dim, seq).
    let q = gen.tensor(&[8, 13, 256])?;
    let k = gen.tensor(&[8, 13, 256])?;
    let t = now_ms();
    let scores = (q.matmul(&k.transpose(1, 2)?.contiguous()?)? / 16.0)?;
    let mask: Vec<f32> = (0..13)
        .flat_map(|i| (0..13).map(move |j| if j > i { f32::NEG_INFINITY } else { 0.0 }))
        .collect();
    let mask = Tensor::from_vec(mask, (1, 13, 13), &Device::Cpu)?;
    let probs = candle_nn::ops::softmax_last_dim(&scores.broadcast_add(&mask)?)?;
    cases.push(record("attention_scores_causal_softmax", t, &probs)?);

    let x = (gen.tensor(&[17, 1024])? * 4.0)?;
    let t = now_ms();
    cases.push(record(
        "rms_normalized_17x1024",
        t,
        &frozen::normalized_op(&x, 1e-6)?,
    )?);

    let x = gen.tensor(&[9, 16, 128])?;
    let t = now_ms();
    cases.push(record("l2_9x16x128", t, &frozen::l2_op(&x)?)?);

    let x = gen.tensor(&[8, 7, 256])?;
    let t = now_ms();
    cases.push(record("rotary_8x7x256", t, &frozen::rotary_op(&x)?)?);

    let x = (gen.tensor(&[9, 2048])? * 6.0)?;
    let t = now_ms();
    let activations = Tensor::cat(&[&x.silu()?, &candle_nn::ops::sigmoid(&x)?], 0)?;
    cases.push(record("silu_sigmoid_9x2048", t, &activations)?);

    // Gated DeltaNet recurrence with model head sizes (H=16, K=V=128).
    let q = frozen::l2_op(&gen.tensor(&[9, 16, 128])?)?;
    let k = frozen::l2_op(&gen.tensor(&[9, 16, 128])?)?;
    let v = gen.tensor(&[9, 16, 128])?;
    let beta = candle_nn::ops::sigmoid(&(gen.tensor(&[9, 16])? * 3.0)?)?;
    let g = gen.tensor(&[9, 16])?.abs()?.neg()?;
    let t = now_ms();
    let delta = frozen::delta_recurrence_op(&q, &k, &v, &beta, &g)?;
    cases.push(record("gated_delta_recurrence_9x16x128", t, &delta)?);

    let t = now_ms();
    let summed = delta.sum_keepdim(D::Minus1)?;
    cases.push(record("reduce_sum_last_dim", t, &summed)?);

    Ok(json!({"schema_version": "kaze_judge.wasm_w0_ops.v1", "cases": cases}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generator_matches_python_float64_replay() {
        // Literals from run_w0.generated(); the driver's GEMM bound depends on this agreement.
        let mut gen = Inputs(0x4a45_4646_5730);
        let first = gen.values(4);
        assert_eq!(first, [-0.0019298792, -0.70661795, 0.0798614, 0.47143698]);
        gen.values(17 * 1024 + 3584 * 1024 + 1024 * 3584 - 4);
        assert_eq!(gen.values(2), [0.10212147, 0.38695478]);
    }

    #[test]
    fn fixtures_are_deterministic_and_finite() -> Result<()> {
        let values = |v: &Value| -> Vec<Value> {
            v["cases"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| json!([c["name"], c["shape"], c["values"]]))
                .collect()
        };
        assert_eq!(values(&run()?), values(&run()?));
        Ok(())
    }
}
