//! Diagnostic: where the library forward spends its time, split finer than matrix products.
//! `profiled` is a copy of src/backbone.rs (as of the commit that adds this file) with exclusive
//! timers around each step; the arithmetic is unchanged and every run checks that its final hidden
//! state is bitwise equal to `pure_jeff::backbone::forward`. A later change to src/backbone.rs
//! needs the copy updated by hand.
//!
//!   cargo run --release --example forward_breakdown -- <manifest> <golden.json>... [--reps N]
use anyhow::{ensure, Context, Result};
use pure_jeff::{
    backbone,
    bundle::{self, Bundle, Manifest},
    tokenize::Tokenizer,
    DecisionRequest, Limits,
};
use std::{
    path::Path,
    time::{Duration, Instant},
};

mod prof {
    use std::{cell::RefCell, time::Instant};

    pub const NAMES: [&str; 23] = [
        "weight_load",
        "bf16_to_f32",
        "embedding",
        "linear_matmul",
        "rmsnorm",
        "residual_add",
        "mlp_silu_mul",
        "conv1d_silu",
        "qk_l2",
        "beta_sigmoid",
        "softplus_g",
        "delta_recurrence",
        "delta_out_norm",
        "z_silu_gate",
        "linear_attn_layout",
        "full_qkv_layout",
        "rotary",
        "kv_repeat",
        "scores_matmul",
        "mask_softmax",
        "probs_matmul",
        "full_out_gate",
        "final_norm",
    ];

    thread_local! {
        static STATE: RefCell<(Vec<f64>, Vec<f64>)> =
            RefCell::new((vec![0.0; NAMES.len()], Vec::new()));
    }

    /// Runs `f`, adding its time minus the time of nested `timed` calls to category `cat`.
    pub fn timed<R>(cat: usize, f: impl FnOnce() -> R) -> R {
        STATE.with(|s| s.borrow_mut().1.push(0.0));
        let start = Instant::now();
        let out = f();
        let elapsed = start.elapsed().as_secs_f64();
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            let nested = s.1.pop().unwrap();
            s.0[cat] += elapsed - nested;
            if let Some(parent) = s.1.last_mut() {
                *parent += elapsed;
            }
        });
        out
    }

    pub fn take() -> Vec<f64> {
        STATE.with(|s| std::mem::replace(&mut s.borrow_mut().0, vec![0.0; NAMES.len()]))
    }
}

mod profiled {
    use super::prof::timed;
    use candle_core::{CpuStorage, DType, Device, Result, Storage, Tensor, D};
    use pure_jeff::WeightSource;

    const WEIGHT_LOAD: usize = 0;
    const BF16_TO_F32: usize = 1;
    const EMBEDDING: usize = 2;
    const LINEAR_MATMUL: usize = 3;
    const RMSNORM: usize = 4;
    const RESIDUAL_ADD: usize = 5;
    const MLP_SILU_MUL: usize = 6;
    const CONV1D_SILU: usize = 7;
    const QK_L2: usize = 8;
    const BETA_SIGMOID: usize = 9;
    const SOFTPLUS_G: usize = 10;
    const DELTA_RECURRENCE: usize = 11;
    const DELTA_OUT_NORM: usize = 12;
    const Z_SILU_GATE: usize = 13;
    const LINEAR_ATTN_LAYOUT: usize = 14;
    const FULL_QKV_LAYOUT: usize = 15;
    const ROTARY: usize = 16;
    const KV_REPEAT: usize = 17;
    const SCORES_MATMUL: usize = 18;
    const MASK_SOFTMAX: usize = 19;
    const PROBS_MATMUL: usize = 20;
    const FULL_OUT_GATE: usize = 21;
    const FINAL_NORM: usize = 22;

    const H: usize = 16;
    const K: usize = 128;
    const V: usize = 128;

    fn weight(weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
        let loaded = timed(WEIGHT_LOAD, || weights.load(name, &Device::Cpu))?;
        timed(BF16_TO_F32, || loaded.to_dtype(DType::F32))
    }

    fn linear(x: &Tensor, weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
        let w = weight(weights, &format!("{name}.weight"))?;
        timed(LINEAR_MATMUL, || x.matmul(&w.t()?))
    }

    fn normalized(x: &Tensor, eps: f64) -> Result<Tensor> {
        x.broadcast_div(&(x.sqr()?.mean_keepdim(D::Minus1)? + eps)?.sqrt()?)
    }

    fn norm(x: &Tensor, weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
        let w = weight(weights, &format!("{name}.weight"))?;
        timed(RMSNORM, || normalized(x, 1e-6)?.broadcast_mul(&(w + 1.0)?))
    }

    fn l2(x: &Tensor) -> Result<Tensor> {
        x.broadcast_div(&(x.sqr()?.sum_keepdim(D::Minus1)? + 1e-6)?.sqrt()?)
    }

    fn silu(v: f32) -> f32 {
        v / (1.0 + (-v).exp())
    }

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
        let hidden = timed(MLP_SILU_MUL, || zip_map(&gate, &up, |g, u| silu(g) * u))?;
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
        let q_gate = linear(x, weights, &format!("{prefix}.q_proj"))?;
        let q_gate = timed(FULL_QKV_LAYOUT, || q_gate.reshape((seq, 8, 512)))?;
        let q_in = timed(FULL_QKV_LAYOUT, || q_gate.narrow(2, 0, 256)?.contiguous())?;
        let q = norm(&q_in, weights, &format!("{prefix}.q_norm"))?;
        let gate = timed(FULL_QKV_LAYOUT, || {
            q_gate
                .narrow(2, 256, 256)?
                .contiguous()?
                .reshape((seq, 2048))
        })?;
        let k_in = linear(x, weights, &format!("{prefix}.k_proj"))?;
        let k_in = timed(FULL_QKV_LAYOUT, || k_in.reshape((seq, 2, 256)))?;
        let k = norm(&k_in, weights, &format!("{prefix}.k_norm"))?;
        let v = linear(x, weights, &format!("{prefix}.v_proj"))?;
        let v = timed(FULL_QKV_LAYOUT, || {
            v.reshape((seq, 2, 256))?.transpose(0, 1)
        })?;
        let q = timed(ROTARY, || rotary(&q.transpose(0, 1)?.contiguous()?))?;
        let k = timed(ROTARY, || rotary(&k.transpose(0, 1)?.contiguous()?))?;
        let repeat = |t: &Tensor| -> Result<Tensor> {
            let heads: Result<Vec<_>> = (0..8).map(|i| t.narrow(0, i / 4, 1)).collect();
            Tensor::cat(&heads?, 0)
        };
        let k = timed(KV_REPEAT, || repeat(&k))?;
        let v = timed(KV_REPEAT, || repeat(&v))?;
        let scores = timed(SCORES_MATMUL, || {
            q.matmul(&k.transpose(1, 2)?.contiguous()?)? / 16.0
        })?;
        let probs = timed(MASK_SOFTMAX, || {
            let mask: Vec<f32> = (0..seq)
                .flat_map(|i| (0..seq).map(move |j| if j > i { f32::NEG_INFINITY } else { 0.0 }))
                .collect();
            let mask = Tensor::from_vec(mask, (1, seq, seq), &Device::Cpu)?;
            candle_nn::ops::softmax_last_dim(&scores.broadcast_add(&mask)?)
        })?;
        let out = timed(PROBS_MATMUL, || probs.matmul(&v))?;
        let gated = timed(FULL_OUT_GATE, || {
            out.transpose(0, 1)?.contiguous()?.reshape((seq, 2048))?
                * candle_nn::ops::sigmoid(&gate)?
        })?;
        linear(&gated, weights, &format!("{prefix}.o_proj"))
    }

    // Copy of src/backbone.rs's delta_recurrence (column-blocked, bitwise equal to the reference).
    fn delta_recurrence(
        q: &Tensor,
        k: &Tensor,
        v: &Tensor,
        beta: &Tensor,
        g: &Tensor,
    ) -> Result<Tensor> {
        const COLUMNS: usize = 32;
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
        let kernel = weight(weights, &format!("{prefix}.conv1d.weight"))?;
        let qkv = timed(CONV1D_SILU, || conv_silu(&qkv, &kernel))?;
        let q = timed(QK_L2, || {
            l2(&qkv.narrow(1, 0, H * K)?.reshape((seq, H, K))?)
        })?;
        let k = timed(QK_L2, || {
            l2(&qkv.narrow(1, H * K, H * K)?.reshape((seq, H, K))?)
        })?;
        let v = timed(LINEAR_ATTN_LAYOUT, || {
            qkv.narrow(1, H * K * 2, H * V)?.reshape((seq, H, V))
        })?;
        let z = linear(x, weights, &format!("{prefix}.in_proj_z"))?;
        let z = timed(LINEAR_ATTN_LAYOUT, || z.reshape((seq, H, V)))?;
        let b = linear(x, weights, &format!("{prefix}.in_proj_b"))?;
        let beta = timed(BETA_SIGMOID, || candle_nn::ops::sigmoid(&b))?;
        let a = linear(x, weights, &format!("{prefix}.in_proj_a"))?;
        let dt_bias = weight(weights, &format!("{prefix}.dt_bias"))?;
        let a_log = weight(weights, &format!("{prefix}.A_log"))?;
        let g = timed(SOFTPLUS_G, || {
            let a = a.broadcast_add(&dt_bias)?;
            // Stable softplus matches PyTorch's beta=1, threshold=20 behavior.
            let softplus: Vec<f32> = a
                .flatten_all()?
                .to_vec1::<f32>()?
                .iter()
                .map(|&v| if v > 20.0 { v } else { v.exp().ln_1p() })
                .collect();
            Tensor::from_vec(softplus, (seq, H), &Device::Cpu)?.broadcast_mul(&a_log.exp()?.neg()?)
        })?;
        let attention = timed(DELTA_RECURRENCE, || delta_recurrence(&q, &k, &v, &beta, &g))?;
        let norm_weight = weight(weights, &format!("{prefix}.norm.weight"))?;
        let attention = timed(DELTA_OUT_NORM, || {
            normalized(&attention, 1e-6)?.broadcast_mul(&norm_weight)
        })?;
        let gated = timed(Z_SILU_GATE, || {
            zip_map(&attention, &z, |a, z| a * silu(z))?.reshape((seq, H * V))
        })?;
        linear(&gated, weights, &format!("{prefix}.out_proj"))
    }

    pub fn forward(weights: &dyn WeightSource, ids: &[u32]) -> Result<Tensor> {
        let seq = ids.len();
        let mut x = timed(EMBEDDING, || {
            let embedding = weights.load("language_model.embed_tokens.weight", &Device::Cpu)?;
            let indices = Tensor::new(ids, &Device::Cpu)?;
            embedding.index_select(&indices, 0)?.to_dtype(DType::F32)
        })?;
        for i in 0..24 {
            let prefix = format!("language_model.layers.{i}");
            let normalized = norm(&x, weights, &format!("{prefix}.input_layernorm"))?;
            let attention = if i % 4 == 3 {
                full_attention(&normalized, weights, &format!("{prefix}.self_attn"))?
            } else {
                linear_attention(&normalized, weights, &format!("{prefix}.linear_attn"))?
            };
            x = timed(RESIDUAL_ADD, || x + attention)?;
            let normalized = norm(&x, weights, &format!("{prefix}.post_attention_layernorm"))?;
            let mlp = mlp(&normalized, weights, &format!("{prefix}.mlp"))?;
            x = timed(RESIDUAL_ADD, || x + mlp)?;
        }
        let normalized = norm(&x, weights, "language_model.norm")?;
        timed(FINAL_NORM, || normalized.narrow(0, seq - 1, 1))
    }
}

#[derive(serde::Deserialize)]
struct Golden {
    request: DecisionRequest,
}

fn main() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let reps = match args.iter().position(|a| a == "--reps") {
        Some(i) => {
            let value = args.remove(i + 1).parse()?;
            args.remove(i);
            value
        }
        None => 3,
    };
    let (manifest, cases) = args
        .split_first()
        .context("usage: forward_breakdown <manifest> <golden.json>... [--reps N]")?;
    ensure!(
        reps >= 1 && !cases.is_empty(),
        "need at least one case and one rep"
    );
    let deadline = Instant::now() + Duration::from_secs(24 * 3600);
    let header: Manifest = bundle::read_json(Path::new(manifest), 2 * 1024 * 1024)?;
    header.policy.validate()?;
    std::env::set_var("RAYON_NUM_THREADS", header.policy.cpu_threads.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", header.policy.cpu_threads.to_string());
    let bundle = Bundle::verify(Path::new(manifest), deadline, false)?;
    let tokenizer = Tokenizer::load(&bundle)?;
    // SAFETY: the verified checkpoint must stay unchanged while the program runs.
    let weights = unsafe {
        candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("model.safetensors"))?
    };
    ensure!(
        candle_core::utils::get_num_threads() == bundle.manifest.policy.cpu_threads,
        "compute threads differ from the bundle policy"
    );
    let bits = |t: &candle_core::Tensor| -> Result<Vec<u32>> {
        Ok(t.flatten_all()?
            .to_vec1::<f32>()?
            .iter()
            .map(|v| v.to_bits())
            .collect())
    };
    for path in cases {
        let golden: Golden = bundle::read_json(Path::new(path), 64 * 1024 * 1024)?;
        let prepared = tokenizer.prepare(
            &bundle.decision,
            &golden.request,
            Limits {
                max_input_bytes: 1024 * 1024,
                max_input_tokens: 8192,
                max_forwards: 1,
                deadline,
            },
        )?;
        let expected = bits(&backbone::forward(&weights, &prepared.ids)?)?;
        for rep in 0..reps {
            prof::take();
            let step = Instant::now();
            let hidden = profiled::forward(&weights, &prepared.ids)?;
            let forward_s = step.elapsed().as_secs_f64();
            let seconds = prof::take();
            ensure!(
                bits(&hidden)? == expected,
                "{path}: profiled forward differs"
            );
            let categories: serde_json::Map<_, _> = prof::NAMES
                .iter()
                .zip(&seconds)
                .map(|(name, s)| ((*name).to_owned(), serde_json::json!(s)))
                .collect();
            println!(
                "{}",
                serde_json::json!({"case": Path::new(path).file_stem().unwrap().to_string_lossy(),
                    "input_tokens": prepared.ids.len(), "rep": rep, "forward_s": forward_s,
                    "timed_s": seconds.iter().sum::<f64>(), "bitwise_equal": true,
                    "seconds": categories})
            );
        }
    }
    Ok(())
}
