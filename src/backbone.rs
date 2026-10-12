//! FP32, text-only, batch-one experiment for the fixed Jeff 0.8B checkpoint.
//! Equations checked against Transformers 5.17.0 Qwen3.5 (Apache-2.0).
//! No cache, padding, image inputs, quantization, or production deadline guarantee.
use crate::WeightSource;
use candle_core::{DType, Device, Result, Tensor, D};

const H: usize = 16;
const K: usize = 128;
const V: usize = 128;

fn weight(weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
    weights.load(name, &Device::Cpu)?.to_dtype(DType::F32)
}

fn linear(x: &Tensor, weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
    x.matmul(&weight(weights, &format!("{name}.weight"))?.t()?)
}

fn normalized(x: &Tensor, eps: f64) -> Result<Tensor> {
    x.broadcast_div(&(x.sqr()?.mean_keepdim(D::Minus1)? + eps)?.sqrt()?)
}

fn norm(x: &Tensor, weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
    normalized(x, 1e-6)?.broadcast_mul(&(weight(weights, &format!("{name}.weight"))? + 1.0)?)
}

fn l2(x: &Tensor) -> Result<Tensor> {
    x.broadcast_div(&(x.sqr()?.sum_keepdim(D::Minus1)? + 1e-6)?.sqrt()?)
}

fn mlp(x: &Tensor, weights: &dyn WeightSource, prefix: &str) -> Result<Tensor> {
    let gate = linear(x, weights, &format!("{prefix}.gate_proj"))?.silu()?;
    let up = linear(x, weights, &format!("{prefix}.up_proj"))?;
    linear(&(gate * up)?, weights, &format!("{prefix}.down_proj"))
}

fn rotary(x: &Tensor) -> Result<Tensor> {
    let (_, seq, _) = x.dims3()?;
    let mut cos = Vec::with_capacity(seq * 64);
    let mut sin = Vec::with_capacity(seq * 64);
    for pos in 0..seq {
        for _ in 0..2 {
            for j in 0..32 {
                let inv = 1.0 / 10_000_000_f32.powf((2 * j) as f32 / 64.0);
                let angle = pos as f32 * inv;
                cos.push(angle.cos());
                sin.push(angle.sin());
            }
        }
    }
    let cos = Tensor::from_vec(cos, (1, seq, 64), &Device::Cpu)?;
    let sin = Tensor::from_vec(sin, (1, seq, 64), &Device::Cpu)?;
    let rotated = x.narrow(2, 0, 64)?;
    let half = Tensor::cat(
        &[
            &rotated.narrow(2, 32, 32)?.neg()?,
            &rotated.narrow(2, 0, 32)?,
        ],
        2,
    )?;
    let out = (rotated.broadcast_mul(&cos)? + half.broadcast_mul(&sin)?)?;
    Tensor::cat(&[&out, &x.narrow(2, 64, 192)?], 2)
}

fn full_attention(x: &Tensor, weights: &dyn WeightSource, prefix: &str) -> Result<Tensor> {
    let seq = x.dim(0)?;
    let q_gate = linear(x, weights, &format!("{prefix}.q_proj"))?.reshape((seq, 8, 512))?;
    let q = norm(
        &q_gate.narrow(2, 0, 256)?.contiguous()?,
        weights,
        &format!("{prefix}.q_norm"),
    )?;
    let gate = q_gate
        .narrow(2, 256, 256)?
        .contiguous()?
        .reshape((seq, 2048))?;
    let k = norm(
        &linear(x, weights, &format!("{prefix}.k_proj"))?.reshape((seq, 2, 256))?,
        weights,
        &format!("{prefix}.k_norm"),
    )?;
    let v = linear(x, weights, &format!("{prefix}.v_proj"))?
        .reshape((seq, 2, 256))?
        .transpose(0, 1)?;
    let q = rotary(&q.transpose(0, 1)?.contiguous()?)?;
    let k = rotary(&k.transpose(0, 1)?.contiguous()?)?;
    let repeat = |t: &Tensor| -> Result<Tensor> {
        let heads: Result<Vec<_>> = (0..8).map(|i| t.narrow(0, i / 4, 1)).collect();
        Tensor::cat(&heads?, 0)
    };
    let k = repeat(&k)?;
    let v = repeat(&v)?;
    let scores = (q.matmul(&k.transpose(1, 2)?.contiguous()?)? / 16.0)?;
    let mask: Vec<f32> = (0..seq)
        .flat_map(|i| (0..seq).map(move |j| if j > i { f32::NEG_INFINITY } else { 0.0 }))
        .collect();
    let mask = Tensor::from_vec(mask, (1, seq, seq), &Device::Cpu)?;
    let probs = candle_nn::ops::softmax_last_dim(&scores.broadcast_add(&mask)?)?;
    let out = probs
        .matmul(&v)?
        .transpose(0, 1)?
        .contiguous()?
        .reshape((seq, 2048))?;
    linear(
        &(out * candle_nn::ops::sigmoid(&gate)?)?,
        weights,
        &format!("{prefix}.o_proj"),
    )
}

// Reference recurrence: S <- exp(g) S; delta <- beta (v - k^T S);
// S <- S + k delta^T; output <- q^T S. No fused/native inference dependency.
fn delta_recurrence(
    q: &Tensor,
    k: &Tensor,
    v: &Tensor,
    beta: &Tensor,
    g: &Tensor,
) -> Result<Tensor> {
    let q = q.to_vec3::<f32>()?;
    let k = k.to_vec3::<f32>()?;
    let v = v.to_vec3::<f32>()?;
    let beta = beta.to_vec2::<f32>()?;
    let g = g.to_vec2::<f32>()?;
    let seq = q.len();
    let mut state = vec![0_f32; H * K * V];
    let mut out = vec![0_f32; seq * H * V];
    for t in 0..seq {
        for h in 0..H {
            let state = &mut state[h * K * V..(h + 1) * K * V];
            let decay = g[t][h].exp();
            for s in state.iter_mut() {
                *s *= decay;
            }
            let mut delta = [0_f32; V];
            for (i, row) in state.as_chunks::<V>().0.iter().enumerate() {
                for (j, value) in row.iter().enumerate() {
                    delta[j] += value * k[t][h][i];
                }
            }
            for (j, d) in delta.iter_mut().enumerate() {
                *d = (v[t][h][j] - *d) * beta[t][h];
            }
            let output = &mut out[(t * H + h) * V..(t * H + h + 1) * V];
            for (i, row) in state.as_chunks_mut::<V>().0.iter_mut().enumerate() {
                let qi = q[t][h][i] / (K as f32).sqrt();
                for (j, s) in row.iter_mut().enumerate() {
                    *s += k[t][h][i] * delta[j];
                    output[j] += *s * qi;
                }
            }
        }
    }
    Tensor::from_vec(out, (seq, H, V), &Device::Cpu)
}

fn linear_attention(x: &Tensor, weights: &dyn WeightSource, prefix: &str) -> Result<Tensor> {
    let seq = x.dim(0)?;
    let qkv = linear(x, weights, &format!("{prefix}.in_proj_qkv"))?;
    let kernel = weight(weights, &format!("{prefix}.conv1d.weight"))?.squeeze(1)?;
    let mut convolved = Tensor::zeros(qkv.shape(), DType::F32, &Device::Cpu)?;
    for j in 0..4 {
        let delay = 3 - j;
        if delay < seq {
            let shifted = qkv.narrow(0, 0, seq - delay)?.pad_with_zeros(0, delay, 0)?;
            convolved =
                (convolved + shifted.broadcast_mul(&kernel.narrow(1, j, 1)?.squeeze(1)?)?)?;
        }
    }
    let qkv = convolved.silu()?;
    let q = l2(&qkv.narrow(1, 0, H * K)?.reshape((seq, H, K))?)?;
    let k = l2(&qkv.narrow(1, H * K, H * K)?.reshape((seq, H, K))?)?;
    let v = qkv.narrow(1, H * K * 2, H * V)?.reshape((seq, H, V))?;
    let z = linear(x, weights, &format!("{prefix}.in_proj_z"))?.reshape((seq, H, V))?;
    let beta = candle_nn::ops::sigmoid(&linear(x, weights, &format!("{prefix}.in_proj_b"))?)?;
    let a = linear(x, weights, &format!("{prefix}.in_proj_a"))?
        .broadcast_add(&weight(weights, &format!("{prefix}.dt_bias"))?)?;
    // Stable softplus matches PyTorch's beta=1, threshold=20 behavior.
    let softplus: Vec<f32> = a
        .flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .map(|&v| if v > 20.0 { v } else { v.exp().ln_1p() })
        .collect();
    let g = Tensor::from_vec(softplus, (seq, H), &Device::Cpu)?
        .broadcast_mul(&weight(weights, &format!("{prefix}.A_log"))?.exp()?.neg()?)?;
    let attention = delta_recurrence(&q, &k, &v, &beta, &g)?;
    let attention = normalized(&attention, 1e-6)?
        .broadcast_mul(&weight(weights, &format!("{prefix}.norm.weight"))?)?;
    linear(
        &(attention * z.silu()?)?.reshape((seq, H * V))?,
        weights,
        &format!("{prefix}.out_proj"),
    )
}

/// Only call with the pinned 0.8B config and an unpadded text sequence.
pub fn forward(weights: &dyn WeightSource, ids: &[u32]) -> Result<Tensor> {
    forward_checked(weights, ids, &|| Ok(()))
}
pub fn forward_checked(
    weights: &dyn WeightSource,
    ids: &[u32],
    check: &dyn Fn() -> Result<()>,
) -> Result<Tensor> {
    check()?;
    let seq = ids.len();
    if seq == 0 || seq > 8192 {
        candle_core::bail!("probe requires 1..=8192 unpadded text tokens")
    }
    let embedding = weights.load("language_model.embed_tokens.weight", &Device::Cpu)?;
    let indices = Tensor::new(ids, &Device::Cpu)?;
    let mut x = embedding.index_select(&indices, 0)?.to_dtype(DType::F32)?;
    drop(embedding);
    for i in 0..24 {
        check()?;
        let prefix = format!("language_model.layers.{i}");
        let normalized = norm(&x, weights, &format!("{prefix}.input_layernorm"))?;
        let attention = if i % 4 == 3 {
            full_attention(&normalized, weights, &format!("{prefix}.self_attn"))?
        } else {
            linear_attention(&normalized, weights, &format!("{prefix}.linear_attn"))?
        };
        x = (x + attention)?;
        let normalized = norm(&x, weights, &format!("{prefix}.post_attention_layernorm"))?;
        x = (x + mlp(&normalized, weights, &format!("{prefix}.mlp"))?)?;
        check()?;
    }
    norm(&x, weights, "language_model.norm")?.narrow(0, seq - 1, 1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delta_update_decay_and_state_isolation() -> Result<()> {
        let mut q = vec![0_f32; 2 * H * K];
        let mut v = vec![0_f32; 2 * H * V];
        for t in 0..2 {
            for h in 0..H {
                q[(t * H + h) * K] = 1.0;
                v[(t * H + h) * V] = if t == 0 { 2.0 } else { 4.0 };
            }
        }
        let q = Tensor::from_vec(q, (2, H, K), &Device::Cpu)?;
        let v = Tensor::from_vec(v, (2, H, V), &Device::Cpu)?;
        let beta = Tensor::full(0.5_f32, (2, H), &Device::Cpu)?;
        let mut decay = vec![0_f32; 2 * H];
        decay[H..].fill(0.5_f32.ln());
        let decay = Tensor::from_vec(decay, (2, H), &Device::Cpu)?;
        let first = delta_recurrence(&q, &q, &v, &beta, &decay)?.to_vec3::<f32>()?;
        let repeat = delta_recurrence(&q, &q, &v, &beta, &decay)?.to_vec3::<f32>()?;
        assert_eq!(first, repeat);
        for (first_head, second_head) in first[0].iter().zip(&first[1]) {
            assert!((first_head[0] - 1.0 / (K as f32).sqrt()).abs() < 1e-6);
            assert!((second_head[0] - 2.25 / (K as f32).sqrt()).abs() < 1e-6);
            assert!(second_head[1..].iter().all(|v| *v == 0.0));
        }
        Ok(())
    }

    #[test]
    fn rope_preserves_unrotated_dimensions_and_zero_position() -> Result<()> {
        let input: Vec<f32> = (0..2 * 256).map(|i| i as f32 / 512.0).collect();
        let x = Tensor::from_vec(input.clone(), (1, 2, 256), &Device::Cpu)?;
        let out = rotary(&x)?.flatten_all()?.to_vec1::<f32>()?;
        assert_eq!(&input[..256], &out[..256]);
        assert_eq!(&input[256 + 64..], &out[256 + 64..]);
        let before: f32 = input[256..256 + 64].iter().map(|v| v * v).sum();
        let after: f32 = out[256..256 + 64].iter().map(|v| v * v).sum();
        assert!((before - after).abs() < 1e-5);
        Ok(())
    }
}
