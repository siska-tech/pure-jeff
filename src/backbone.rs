//! FP32, text-only, batch-one experiment for the fixed Jeff 0.8B checkpoint.
//! Equations checked against Transformers 5.17.0 Qwen3.5 (Apache-2.0).
//! No cache, padding, image inputs, quantization, or production deadline guarantee.
use crate::WeightSource;
use candle_core::{CpuStorage, Device, Result, Storage, Tensor, D};

const H: usize = 16;
const K: usize = 128;
const V: usize = 128;

fn weight(weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
    weights.load_f32(name)
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

// The element-wise steps below compute each element with the same operations, in the same order,
// as the Candle ops they replace, so the results are bitwise identical (see the tests). Sums,
// means, softmax and matrix products stay in Candle: their summation order is Candle's.

/// Candle's f32 SiLU, written out so it can be fused with its neighbours.
fn silu(v: f32) -> f32 {
    v / (1.0 + (-v).exp())
}

/// Calls `f` with the tensor's f32 elements in row-major order, without a copy when contiguous.
fn with_f32<R>(t: &Tensor, f: impl FnOnce(&[f32]) -> R) -> Result<R> {
    {
        let (storage, layout) = t.storage_and_layout();
        if let (Storage::Cpu(CpuStorage::F32(data)), Some((start, end))) =
            (&*storage, layout.contiguous_offsets())
        {
            return Ok(f(&data[start..end]));
        }
    }
    Ok(f(&t.flatten_all()?.to_vec1::<f32>()?))
}

/// `f(a, b)` for each pair of elements of two tensors of the same shape.
fn zip_map(a: &Tensor, b: &Tensor, f: impl Fn(f32, f32) -> f32) -> Result<Tensor> {
    if a.shape() != b.shape() {
        candle_core::bail!("shape mismatch: {:?} and {:?}", a.shape(), b.shape())
    }
    let out = with_f32(a, |a| {
        with_f32(b, |b| a.iter().zip(b).map(|(&x, &y)| f(x, y)).collect())
    })??;
    Tensor::from_vec(out, a.shape(), &Device::Cpu)
}

fn mlp(x: &Tensor, weights: &dyn WeightSource, prefix: &str) -> Result<Tensor> {
    let gate = linear(x, weights, &format!("{prefix}.gate_proj"))?;
    let up = linear(x, weights, &format!("{prefix}.up_proj"))?;
    let hidden = zip_map(&gate, &up, |g, u| silu(g) * u)?;
    linear(&hidden, weights, &format!("{prefix}.down_proj"))
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

// Columns of one head's state processed together; 128 rows of them (16 KiB) stay in L1 cache.
const COLUMNS: usize = 32;

// Recurrence: S <- exp(g) S; delta <- beta (v - k^T S); S <- S + k delta^T; output <- q^T S.
// Column j of S, delta and output depends only on column j, so each head runs in blocks of
// COLUMNS columns over every token. Every element sees the same operations in the same order as
// the token-major reference in the tests (no FMA), so the result is bitwise identical.
fn delta_recurrence(
    q: &Tensor,
    k: &Tensor,
    v: &Tensor,
    beta: &Tensor,
    g: &Tensor,
) -> Result<Tensor> {
    let seq = q.dim(0)?;
    let scale = (K as f32).sqrt();
    let q: Vec<f32> = q
        .flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .map(|x| x / scale)
        .collect();
    let k = k.flatten_all()?.to_vec1::<f32>()?;
    let v = v.flatten_all()?.to_vec1::<f32>()?;
    let beta = beta.flatten_all()?.to_vec1::<f32>()?;
    let decay: Vec<f32> = g
        .flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .map(|g| g.exp())
        .collect();
    let mut out = vec![0_f32; seq * H * V];
    for h in 0..H {
        for column in (0..V).step_by(COLUMNS) {
            let mut state = [[0_f32; COLUMNS]; K];
            for t in 0..seq {
                let at = t * H + h;
                let (q, k) = (&q[at * K..][..K], &k[at * K..][..K]);
                let mut delta = [0_f32; COLUMNS];
                for (row, ki) in state.iter_mut().zip(k) {
                    for (s, d) in row.iter_mut().zip(&mut delta) {
                        *s *= decay[at];
                        *d += *s * ki;
                    }
                }
                for (d, vj) in delta.iter_mut().zip(&v[at * V + column..][..COLUMNS]) {
                    *d = (vj - *d) * beta[at];
                }
                let mut output = [0_f32; COLUMNS];
                for ((row, ki), qi) in state.iter_mut().zip(k).zip(q) {
                    for ((s, d), o) in row.iter_mut().zip(&delta).zip(&mut output) {
                        *s += ki * d;
                        *o += *s * qi;
                    }
                }
                out[at * V + column..][..COLUMNS].copy_from_slice(&output);
            }
        }
    }
    Tensor::from_vec(out, (seq, H, V), &Device::Cpu)
}

// Causal depthwise convolution over tokens (4 taps), then SiLU. Each output starts at 0.0 and
// adds tap j = 0..4 (the input `3 - j` tokens earlier, zero before the first token) times its
// weight, as the zero-initialised sum of shifted, padded products did.
fn conv_silu(x: &Tensor, kernel: &Tensor) -> Result<Tensor> {
    let (seq, channels) = x.dims2()?;
    let kernel = kernel.squeeze(1)?.t()?.contiguous()?.to_vec2::<f32>()?;
    if kernel.len() != 4 || kernel[0].len() != channels {
        candle_core::bail!("conv1d kernel must be (channels, 1, 4)")
    }
    let out = with_f32(x, |x| {
        let mut out = vec![0_f32; seq * channels];
        for (t, row) in out.chunks_exact_mut(channels).enumerate() {
            for (j, taps) in kernel.iter().enumerate() {
                let delay = 3 - j;
                if delay >= seq {
                    continue;
                }
                if let Some(source) = t.checked_sub(delay) {
                    let input = &x[source * channels..][..channels];
                    for ((o, i), w) in row.iter_mut().zip(input).zip(taps) {
                        *o += i * w;
                    }
                } else {
                    for (o, w) in row.iter_mut().zip(taps) {
                        *o += 0.0 * w;
                    }
                }
            }
            for o in row.iter_mut() {
                *o = silu(*o);
            }
        }
        out
    })?;
    Tensor::from_vec(out, (seq, channels), &Device::Cpu)
}

fn linear_attention(x: &Tensor, weights: &dyn WeightSource, prefix: &str) -> Result<Tensor> {
    let seq = x.dim(0)?;
    let qkv = linear(x, weights, &format!("{prefix}.in_proj_qkv"))?;
    let qkv = conv_silu(&qkv, &weight(weights, &format!("{prefix}.conv1d.weight"))?)?;
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
        &zip_map(&attention, &z, |a, z| a * silu(z))?.reshape((seq, H * V))?,
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
    let mut x = weights.load_f32_rows("language_model.embed_tokens.weight", ids)?;
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
    use candle_core::DType;

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

    // The token-major recurrence that pure-jeff 0.1.0 shipped (and runtime/wasm/frozen keeps).
    fn reference_recurrence(
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

    #[test]
    fn delta_recurrence_is_bitwise_equal_to_the_reference() -> Result<()> {
        let mut seed = 0x2545_f491_4f6c_dd1d_u64;
        for seq in [1, 3, 37] {
            let q = l2(&Tensor::from_vec(
                uniform(&mut seed, seq * H * K, -1.0, 1.0),
                (seq, H, K),
                &Device::Cpu,
            )?)?;
            let k = l2(&Tensor::from_vec(
                uniform(&mut seed, seq * H * K, -1.0, 1.0),
                (seq, H, K),
                &Device::Cpu,
            )?)?;
            let v = Tensor::from_vec(
                uniform(&mut seed, seq * H * V, -4.0, 4.0),
                (seq, H, V),
                &Device::Cpu,
            )?;
            let beta = Tensor::from_vec(
                uniform(&mut seed, seq * H, 0.0, 1.0),
                (seq, H),
                &Device::Cpu,
            )?;
            let g = Tensor::from_vec(
                uniform(&mut seed, seq * H, -3.0, 0.0),
                (seq, H),
                &Device::Cpu,
            )?;
            let bits = |t: Tensor| -> Result<Vec<u32>> {
                Ok(t.flatten_all()?
                    .to_vec1::<f32>()?
                    .iter()
                    .map(|v| v.to_bits())
                    .collect())
            };
            assert_eq!(
                bits(delta_recurrence(&q, &k, &v, &beta, &g)?)?,
                bits(reference_recurrence(&q, &k, &v, &beta, &g)?)?,
                "seq {seq}"
            );
        }
        Ok(())
    }

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

    fn bits(t: &Tensor) -> Result<Vec<u32>> {
        Ok(t.flatten_all()?
            .to_vec1::<f32>()?
            .iter()
            .map(|v| v.to_bits())
            .collect())
    }

    #[test]
    fn fused_element_wise_steps_are_bitwise_equal_to_candle_ops() -> Result<()> {
        let mut seed = 0x9e37_79b9_7f4a_7c15_u64;
        let channels = 40;
        let kernel = Tensor::from_vec(
            uniform(&mut seed, channels * 4, -1.0, 1.0),
            (channels, 1, 4),
            &Device::Cpu,
        )?;
        for seq in [1, 2, 3, 4, 9] {
            let x = Tensor::from_vec(
                uniform(&mut seed, seq * channels, -6.0, 6.0),
                (seq, channels),
                &Device::Cpu,
            )?;
            // The Candle sequence that linear_attention used before conv_silu.
            let taps = kernel.squeeze(1)?;
            let mut convolved = Tensor::zeros(x.shape(), DType::F32, &Device::Cpu)?;
            for j in 0..4 {
                let delay = 3 - j;
                if delay < seq {
                    let shifted = x.narrow(0, 0, seq - delay)?.pad_with_zeros(0, delay, 0)?;
                    convolved =
                        (convolved + shifted.broadcast_mul(&taps.narrow(1, j, 1)?.squeeze(1)?)?)?;
                }
            }
            assert_eq!(
                bits(&conv_silu(&x, &kernel)?)?,
                bits(&convolved.silu()?)?,
                "seq {seq}"
            );
            let y = Tensor::from_vec(
                uniform(&mut seed, seq * channels, -6.0, 6.0),
                (seq, channels),
                &Device::Cpu,
            )?;
            assert_eq!(
                bits(&zip_map(&x, &y, |g, u| silu(g) * u)?)?,
                bits(&(x.silu()? * &y)?)?
            );
            assert_eq!(
                bits(&zip_map(&x, &y, |a, z| a * silu(z))?)?,
                bits(&(&x * y.silu()?)?)?
            );
            // A non-contiguous input takes the copying path.
            let xt = x.t()?;
            let yt = y.t()?.contiguous()?;
            assert_eq!(
                bits(&zip_map(&xt, &yt, |g, u| silu(g) * u)?)?,
                bits(&(xt.silu()? * &yt)?)?
            );
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
