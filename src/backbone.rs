//! FP32, text-only, batch-one experiment for the fixed Jeff 0.8B checkpoint.
//! Equations checked against Transformers 5.17.0 Qwen3.5 (Apache-2.0).
//! No cache, padding, image inputs, quantization, or production deadline guarantee.
use crate::WeightSource;
use candle_core::{CpuStorage, Device, InplaceOp1, Layout, Result, Storage, Tensor, D};
use std::cell::{Cell, RefCell};

const H: usize = 16;
const K: usize = 128;
const V: usize = 128;

fn linear(x: &Tensor, weights: &Weights, name: &str) -> Result<Tensor> {
    weights.with(&format!("{name}.weight"), |w| x.matmul(&w.t()?))
}

fn normalized(x: &Tensor, eps: f64) -> Result<Tensor> {
    x.broadcast_div(&(x.sqr()?.mean_keepdim(D::Minus1)? + eps)?.sqrt()?)
}

fn norm(x: &Tensor, weights: &Weights, name: &str) -> Result<Tensor> {
    let x = normalized(x, 1e-6)?;
    weights.with(&format!("{name}.weight"), |w| x.broadcast_mul(&(w + 1.0)?))
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

fn mlp(x: &Tensor, weights: &Weights, prefix: &str) -> Result<Tensor> {
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

/// Query rows per attention block (see `full_attention`). Sequences up to this length run as
/// one block, exactly as before blocks were introduced.
pub const QUERY_BLOCK: usize = 512;

/// Causal attention for query rows `start..start + rows` against all `seq` keys: the scores,
/// mask, softmax and value product of those rows only. Every row still spans every key (masked
/// ones contribute exp(-inf) = 0 as before), so each row's values come from the same products,
/// sums and softmax over the same length as with one block.
fn attention_rows(
    q: &Tensor,
    kt: &Tensor,
    v: &Tensor,
    start: usize,
    rows: usize,
) -> Result<Tensor> {
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
    probs.matmul(v)
}

fn full_attention(
    x: &Tensor,
    weights: &Weights,
    prefix: &str,
    query_block: usize,
    check: &dyn Fn() -> Result<()>,
) -> Result<Tensor> {
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
    let kt = k.transpose(1, 2)?.contiguous()?;
    // Scores, mask and probabilities exist for one block of query rows at a time, so their
    // memory is (8, block, seq) instead of (8, seq, seq): 128 MiB instead of 2 GiB each at 8192.
    let block = query_block.max(1);
    let out = if seq <= block {
        attention_rows(&q, &kt, &v, 0, seq)?
    } else {
        let mut parts = Vec::with_capacity(seq.div_ceil(block));
        for start in (0..seq).step_by(block) {
            check()?;
            parts.push(attention_rows(&q, &kt, &v, start, block.min(seq - start))?);
        }
        Tensor::cat(&parts, 1)?
    };
    let out = out.transpose(0, 1)?.contiguous()?.reshape((seq, 2048))?;
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

fn linear_attention(x: &Tensor, weights: &Weights, prefix: &str) -> Result<Tensor> {
    let seq = x.dim(0)?;
    let qkv = linear(x, weights, &format!("{prefix}.in_proj_qkv"))?;
    let qkv = weights.with(&format!("{prefix}.conv1d.weight"), |k| conv_silu(&qkv, k))?;
    let q = l2(&qkv.narrow(1, 0, H * K)?.reshape((seq, H, K))?)?;
    let k = l2(&qkv.narrow(1, H * K, H * K)?.reshape((seq, H, K))?)?;
    let v = qkv.narrow(1, H * K * 2, H * V)?.reshape((seq, H, V))?;
    let z = linear(x, weights, &format!("{prefix}.in_proj_z"))?.reshape((seq, H, V))?;
    let beta = candle_nn::ops::sigmoid(&linear(x, weights, &format!("{prefix}.in_proj_b"))?)?;
    let a = linear(x, weights, &format!("{prefix}.in_proj_a"))?;
    let a = weights.with(&format!("{prefix}.dt_bias"), |b| a.broadcast_add(b))?;
    // Stable softplus matches PyTorch's beta=1, threshold=20 behavior.
    let softplus: Vec<f32> = a
        .flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .map(|&v| if v > 20.0 { v } else { v.exp().ln_1p() })
        .collect();
    let softplus = Tensor::from_vec(softplus, (seq, H), &Device::Cpu)?;
    let g = weights.with(&format!("{prefix}.A_log"), |a| {
        softplus.broadcast_mul(&a.exp()?.neg()?)
    })?;
    let attention = delta_recurrence(&q, &k, &v, &beta, &g)?;
    let attention = normalized(&attention, 1e-6)?;
    let attention = weights.with(&format!("{prefix}.norm.weight"), |w| {
        attention.broadcast_mul(w)
    })?;
    linear(
        &zip_map(&attention, &z, |a, z| a * silu(z))?.reshape((seq, H * V))?,
        weights,
        &format!("{prefix}.out_proj"),
    )
}

/// Writes one tensor of `source`, converted to F32, into a buffer in place.
struct Fill<'a> {
    source: &'a dyn WeightSource,
    name: &'a str,
    converted: Cell<bool>,
}

impl InplaceOp1 for Fill<'_> {
    fn name(&self) -> &'static str {
        "pure-jeff-fill-f32"
    }

    fn cpu_fwd(&self, storage: &mut CpuStorage, layout: &Layout) -> Result<()> {
        let (CpuStorage::F32(data), Some((start, end))) = (storage, layout.contiguous_offsets())
        else {
            candle_core::bail!("conversion buffer must be contiguous F32")
        };
        self.converted.set(self.source.load_f32_into(
            self.name,
            layout.dims(),
            &mut data[start..end],
        )?);
        Ok(())
    }
}

fn same_storage(a: &Tensor, b: &Tensor) -> bool {
    std::ptr::eq(&*a.storage_and_layout().0, &*b.storage_and_layout().0)
}

/// The weights of one forward. Each weight is lent to a closure only, and every use is a
/// product, element-wise op or copy that makes a new tensor, so at most one weight is in use
/// at a time. With a buffer, every weight a source converts (`convertible_shape`) is converted
/// into the same F32 buffer instead of newly allocated memory: after the first layers the
/// forward writes only to pages already mapped, and the memory held for weights stays that of
/// the largest one. A closure's result that shares the buffer's storage is an error, so a lent
/// weight cannot outlive its closure through the result. Tensors a source keeps (retained F32
/// weights) are lent as they are. The buffer belongs to this forward only.
struct Weights<'a> {
    source: &'a dyn WeightSource,
    buffer: Option<RefCell<Option<Tensor>>>,
}

impl Weights<'_> {
    fn with(&self, name: &str, f: impl FnOnce(&Tensor) -> Result<Tensor>) -> Result<Tensor> {
        let (Some(buffer), Some(shape)) = (&self.buffer, self.source.convertible_shape(name))
        else {
            return f(&self.source.load_f32(name)?);
        };
        let count: usize = shape.iter().product();
        let current = buffer.borrow().clone();
        let storage = match current {
            Some(t) if t.elem_count() >= count => t,
            _ => {
                let fresh = Tensor::zeros(count, candle_core::DType::F32, &Device::Cpu)?;
                *buffer.borrow_mut() = Some(fresh.clone());
                fresh
            }
        };
        let weight = storage.narrow(0, 0, count)?.reshape(shape)?;
        let fill = Fill {
            source: self.source,
            name,
            converted: Cell::new(false),
        };
        weight.inplace_op1(&fill)?;
        if !fill.converted.get() {
            return f(&self.source.load_f32(name)?);
        }
        let out = f(&weight)?;
        if same_storage(&out, &storage) {
            candle_core::bail!("{name}: a lent weight was kept past its use")
        }
        Ok(out)
    }

    fn rows(&self, name: &str, ids: &[u32]) -> Result<Tensor> {
        self.source.load_f32_rows(name, ids)
    }
}

/// Only call with the pinned 0.8B config and an unpadded text sequence.
pub fn forward(weights: &dyn WeightSource, ids: &[u32]) -> Result<Tensor> {
    forward_checked(weights, ids, &|| Ok(()))
}

/// [`forward_checked_with`] converting every weight into new memory.
pub fn forward_checked(
    weights: &dyn WeightSource,
    ids: &[u32],
    check: &dyn Fn() -> Result<()>,
) -> Result<Tensor> {
    forward_checked_with(weights, ids, check, false)
}

/// The forward with `check` before and after every layer. With `reuse_buffers`, every converted
/// weight is written into one buffer that is lent to each use in turn; the result is bitwise the
/// same either way.
pub fn forward_checked_with(
    weights: &dyn WeightSource,
    ids: &[u32],
    check: &dyn Fn() -> Result<()>,
    reuse_buffers: bool,
) -> Result<Tensor> {
    forward_blocks(weights, ids, check, reuse_buffers, QUERY_BLOCK)
}

/// [`forward_checked_with`] with `query_block` query rows per attention block (diagnostics;
/// `usize::MAX` runs every sequence as one block). `check` also runs between blocks.
#[doc(hidden)]
pub fn forward_blocks(
    weights: &dyn WeightSource,
    ids: &[u32],
    check: &dyn Fn() -> Result<()>,
    reuse_buffers: bool,
    query_block: usize,
) -> Result<Tensor> {
    let weights = Weights {
        source: weights,
        buffer: reuse_buffers.then(|| RefCell::new(None)),
    };
    check()?;
    let seq = ids.len();
    if seq == 0 || seq > 8192 {
        candle_core::bail!("probe requires 1..=8192 unpadded text tokens")
    }
    let mut x = weights.rows("language_model.embed_tokens.weight", ids)?;
    for i in 0..24 {
        check()?;
        let prefix = format!("language_model.layers.{i}");
        let normalized = norm(&x, &weights, &format!("{prefix}.input_layernorm"))?;
        let attention = if i % 4 == 3 {
            full_attention(
                &normalized,
                &weights,
                &format!("{prefix}.self_attn"),
                query_block,
                check,
            )?
        } else {
            linear_attention(&normalized, &weights, &format!("{prefix}.linear_attn"))?
        };
        x = (x + attention)?;
        let normalized = norm(&x, &weights, &format!("{prefix}.post_attention_layernorm"))?;
        x = (x + mlp(&normalized, &weights, &format!("{prefix}.mlp"))?)?;
        check()?;
    }
    norm(&x, &weights, "language_model.norm")?.narrow(0, seq - 1, 1)
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

    /// A safetensors file of BF16 tensors whose values are `seed + index` (exact in BF16).
    fn bf16_file(tensors: &[(&str, &[usize], f32)]) -> Vec<u8> {
        let mut header = serde_json::Map::new();
        let mut data = Vec::new();
        for (name, shape, seed) in tensors {
            let count: usize = shape.iter().product();
            let start = data.len();
            for i in 0..count {
                let value = half::bf16::from_f32(seed + i as f32);
                data.extend_from_slice(&value.to_le_bytes());
            }
            header.insert(
                (*name).into(),
                serde_json::json!({"dtype": "BF16", "shape": shape, "data_offsets": [start, data.len()]}),
            );
        }
        let header = serde_json::to_vec(&header).unwrap();
        let mut file = (header.len() as u64).to_le_bytes().to_vec();
        file.extend(header);
        file.extend(data);
        file
    }

    fn lent(weights: &Weights, name: &str) -> Result<Tensor> {
        weights.with(name, |w| w.copy())
    }

    #[test]
    fn one_buffer_gives_every_weight_its_own_values() -> Result<()> {
        let file = bf16_file(&[
            ("language_model.layers.0.mlp.up_proj.weight", &[2, 3], 1.0),
            ("language_model.layers.1.mlp.up_proj.weight", &[2, 3], 10.0),
            (
                "language_model.layers.2.mlp.down_proj.weight",
                &[3, 2],
                20.0,
            ),
            (
                "language_model.layers.3.linear_attn.in_proj_qkv.weight",
                &[4, 3],
                30.0,
            ),
            ("language_model.layers.4.input_layernorm.weight", &[3], 40.0),
        ]);
        let source = candle_core::safetensors::SliceSafetensors::new(&file)?;
        let weights = Weights {
            source: &source,
            buffer: Some(RefCell::new(None)),
        };
        let names = [
            "language_model.layers.0.mlp.up_proj.weight",
            "language_model.layers.1.mlp.up_proj.weight",
            "language_model.layers.2.mlp.down_proj.weight",
            "language_model.layers.3.linear_attn.in_proj_qkv.weight",
            "language_model.layers.4.input_layernorm.weight",
            "language_model.layers.0.mlp.up_proj.weight",
        ];
        for name in names {
            let got = lent(&weights, name)?;
            let expected = source.load_f32(name)?;
            assert_eq!(got.dims(), expected.dims(), "{name}");
            assert_eq!(bits(&got)?, bits(&expected)?, "{name}");
        }
        // The buffer grew to the largest weight (12 values) and was kept.
        let buffer = weights.buffer.as_ref().unwrap().borrow().clone().unwrap();
        assert_eq!(buffer.elem_count(), 12);
        // A weight lent twice in a row is written into the same storage.
        let mut seen = None;
        for name in &names[..2] {
            weights.with(name, |w| {
                let (storage, _) = w.storage_and_layout();
                let address = &*storage as *const _ as usize;
                assert!(
                    seen.is_none_or(|s| s == address),
                    "the buffer was not reused"
                );
                seen = Some(address);
                w.copy()
            })?;
        }
        Ok(())
    }

    #[test]
    fn a_result_that_keeps_the_lent_weight_is_rejected() -> Result<()> {
        let file = bf16_file(&[("language_model.layers.0.mlp.up_proj.weight", &[2, 3], 1.0)]);
        let source = candle_core::safetensors::SliceSafetensors::new(&file)?;
        let weights = Weights {
            source: &source,
            buffer: Some(RefCell::new(None)),
        };
        let name = "language_model.layers.0.mlp.up_proj.weight";
        assert!(weights.with(name, |w| Ok(w.clone())).is_err());
        assert!(weights.with(name, |w| w.t()).is_err());
        assert!(weights.with(name, |w| w.copy()).is_ok());
        // Without a buffer nothing is lent from shared memory.
        let plain = Weights {
            source: &source,
            buffer: None,
        };
        assert!(plain.with(name, |w| Ok(w.clone())).is_ok());
        Ok(())
    }

    #[test]
    fn retained_tensors_are_lent_as_kept_and_never_overwritten() -> Result<()> {
        let file = bf16_file(&[
            ("language_model.layers.0.mlp.up_proj.weight", &[2, 3], 1.0),
            ("language_model.layers.1.mlp.up_proj.weight", &[2, 3], 10.0),
            ("language_model.embed_tokens.weight", &[4, 3], 50.0),
        ]);
        let mapped = candle_core::safetensors::SliceSafetensors::new(&file)?;
        let retained = crate::weights::Retained::new(
            candle_core::safetensors::SliceSafetensors::new(&file)?,
            ["language_model.layers.0.mlp.up_proj.weight"],
            &mut || Ok(()),
        )?;
        assert_eq!(retained.retained_bytes(), 6 * 4);
        let weights = Weights {
            source: &retained,
            buffer: Some(RefCell::new(None)),
        };
        let layer0 = "language_model.layers.0.mlp.up_proj.weight";
        let layer1 = "language_model.layers.1.mlp.up_proj.weight";
        let kept = bits(&lent(&weights, layer0)?)?;
        assert!(
            weights.buffer.as_ref().unwrap().borrow().is_none(),
            "a kept tensor used the buffer"
        );
        // A kept tensor may be returned as it is (it is not shared memory).
        assert!(weights.with(layer0, |w| Ok(w.clone())).is_ok());
        assert_eq!(
            bits(&lent(&weights, layer1)?)?,
            bits(&mapped.load_f32(layer1)?)?
        );
        assert_eq!(bits(&retained.load_f32(layer0)?)?, kept);
        assert_eq!(kept, bits(&mapped.load_f32(layer0)?)?);
        let rows = weights.rows("language_model.embed_tokens.weight", &[3, 1])?;
        assert_eq!(
            bits(&rows)?,
            bits(&mapped.load_f32_rows("language_model.embed_tokens.weight", &[3, 1])?)?
        );
        Ok(())
    }

    #[test]
    fn a_failed_retention_returns_the_error() -> Result<()> {
        let file = bf16_file(&[
            ("language_model.layers.0.mlp.up_proj.weight", &[2, 3], 1.0),
            ("language_model.layers.1.mlp.up_proj.weight", &[2, 3], 10.0),
        ]);
        let mut calls = 0;
        let result = crate::weights::Retained::new(
            candle_core::safetensors::SliceSafetensors::new(&file)?,
            [
                "language_model.layers.0.mlp.up_proj.weight",
                "language_model.layers.1.mlp.up_proj.weight",
            ],
            &mut || {
                calls += 1;
                if calls > 1 {
                    candle_core::bail!("deadline exceeded")
                }
                Ok(())
            },
        );
        assert!(result.is_err());
        let missing = crate::weights::Retained::new(
            candle_core::safetensors::SliceSafetensors::new(&file)?,
            ["language_model.layers.9.mlp.up_proj.weight"],
            &mut || Ok(()),
        );
        assert!(missing.is_err());
        Ok(())
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
    fn attention_in_query_blocks_is_bitwise_equal_to_one_block() -> Result<()> {
        let mut seed = 0x5eed_u64;
        for seq in [1, 7, 8, 9, 37] {
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
            let whole = bits(&attention_rows(&q, &kt, &v, 0, seq)?)?;
            for block in [1, 3, 8] {
                let parts: Vec<Tensor> = (0..seq)
                    .step_by(block)
                    .map(|start| attention_rows(&q, &kt, &v, start, block.min(seq - start)))
                    .collect::<Result<_>>()?;
                assert_eq!(
                    bits(&Tensor::cat(&parts, 1)?)?,
                    whole,
                    "seq {seq}, block {block}"
                );
            }
        }
        Ok(())
    }

    #[test]
    fn a_query_block_sees_exactly_its_causal_prefix() -> Result<()> {
        // Row i of the block starting at 5 must weight keys 0..=5+i only: with equal scores the
        // value of every allowed key is averaged, so value j = j gives the mean of 0..=i+5.
        let seq = 9;
        let q = Tensor::zeros((8, seq, 256), DType::F32, &Device::Cpu)?;
        let kt = Tensor::zeros((8, 256, seq), DType::F32, &Device::Cpu)?;
        let values: Vec<f32> = (0..8 * seq * 256)
            .map(|i| ((i / 256) % seq) as f32)
            .collect();
        let v = Tensor::from_vec(values, (8, seq, 256), &Device::Cpu)?;
        let out = attention_rows(&q, &kt, &v, 5, 3)?;
        assert_eq!(out.dims(), [8, 3, 256]);
        let rows = out
            .narrow(0, 0, 1)?
            .squeeze(0)?
            .narrow(1, 0, 1)?
            .squeeze(1)?
            .to_vec1::<f32>()?;
        for (i, value) in rows.iter().enumerate() {
            let last = 5 + i;
            assert!((value - last as f32 / 2.0).abs() < 1e-5, "row {i}: {value}");
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
