//! Diagnostic: where the library forward spends its time, split finer than matrix products.
//! `profiled` is a copy of src/backbone.rs with exclusive timers around each step, updated to the
//! default path of 0.2.0: every weight is converted into one buffer reused for the whole forward,
//! and full attention runs in blocks of `backbone::QUERY_BLOCK` query rows. The arithmetic is
//! unchanged and every run checks that its final hidden state is bitwise equal to
//! `pure_jeff::backbone::forward`. A later change to src/backbone.rs needs the copy updated by
//! hand. Compute threads come from the bundle policy (`cpu_threads`).
//!
//!   cargo run --release --example forward_breakdown -- <manifest> <golden.json>... [--reps N] [--parallel-heads]
//!
//! `--parallel-heads` is an experiment: the DeltaNet heads run on the compute threads.
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

    pub const NAMES: [&str; 22] = [
        "weight_load_f32",
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
    use candle_core::{CpuStorage, Device, InplaceOp1, Layout, Result, Storage, Tensor, D};
    use pure_jeff::WeightSource;
    use std::cell::{Cell, RefCell};
    use std::sync::atomic::{AtomicBool, Ordering};

    /// Experiment (`--parallel-heads`): run the 16 independent DeltaNet heads on the compute
    /// threads. Off by default; the library is not changed.
    pub static PARALLEL_HEADS: AtomicBool = AtomicBool::new(false);

    const WEIGHT_LOAD_F32: usize = 0;
    const EMBEDDING: usize = 1;
    const LINEAR_MATMUL: usize = 2;
    const RMSNORM: usize = 3;
    const RESIDUAL_ADD: usize = 4;
    const MLP_SILU_MUL: usize = 5;
    const CONV1D_SILU: usize = 6;
    const QK_L2: usize = 7;
    const BETA_SIGMOID: usize = 8;
    const SOFTPLUS_G: usize = 9;
    const DELTA_RECURRENCE: usize = 10;
    const DELTA_OUT_NORM: usize = 11;
    const Z_SILU_GATE: usize = 12;
    const LINEAR_ATTN_LAYOUT: usize = 13;
    const FULL_QKV_LAYOUT: usize = 14;
    const ROTARY: usize = 15;
    const KV_REPEAT: usize = 16;
    const SCORES_MATMUL: usize = 17;
    const MASK_SOFTMAX: usize = 18;
    const PROBS_MATMUL: usize = 19;
    const FULL_OUT_GATE: usize = 20;
    const FINAL_NORM: usize = 21;

    const H: usize = 16;
    const K: usize = 128;
    const V: usize = 128;

    struct Fill<'a> {
        source: &'a dyn WeightSource,
        name: &'a str,
        converted: Cell<bool>,
    }

    impl InplaceOp1 for Fill<'_> {
        fn name(&self) -> &'static str {
            "profiled-fill-f32"
        }

        fn cpu_fwd(&self, storage: &mut CpuStorage, layout: &Layout) -> Result<()> {
            let (CpuStorage::F32(data), Some((start, end))) =
                (storage, layout.contiguous_offsets())
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

    thread_local! {
        // The library's per-forward conversion buffer (reset at the start of each forward).
        static BUFFER: RefCell<Option<Tensor>> = const { RefCell::new(None) };
    }

    /// The weight, converted into the shared buffer as the library's default path does. The
    /// caller must use it before asking for the next weight, as the library's lending ensures.
    fn weight(weights: &dyn WeightSource, name: &str) -> Result<Tensor> {
        timed(WEIGHT_LOAD_F32, || {
            let Some(shape) = weights.convertible_shape(name) else {
                return weights.load_f32(name);
            };
            let count: usize = shape.iter().product();
            let current = BUFFER.with(|b| b.borrow().clone());
            let storage = match current {
                Some(t) if t.elem_count() >= count => t,
                _ => {
                    let fresh = Tensor::zeros(count, candle_core::DType::F32, &Device::Cpu)?;
                    BUFFER.with(|b| *b.borrow_mut() = Some(fresh.clone()));
                    fresh
                }
            };
            let weight = storage.narrow(0, 0, count)?.reshape(shape)?;
            let fill = Fill {
                source: weights,
                name,
                converted: Cell::new(false),
            };
            weight.inplace_op1(&fill)?;
            if fill.converted.get() {
                Ok(weight)
            } else {
                weights.load_f32(name)
            }
        })
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
        let kt = timed(SCORES_MATMUL, || k.transpose(1, 2)?.contiguous())?;
        let block = pure_jeff::backbone::QUERY_BLOCK;
        let mut parts = Vec::new();
        for start in (0..seq).step_by(block) {
            let rows = block.min(seq - start);
            let scores = timed(SCORES_MATMUL, || {
                let q = if rows == seq {
                    q.clone()
                } else {
                    q.narrow(1, start, rows)?.contiguous()?
                };
                q.matmul(&kt)? / 16.0
            })?;
            let probs = timed(MASK_SOFTMAX, || {
                let mask: Vec<f32> = (start..start + rows)
                    .flat_map(|i| {
                        (0..seq).map(move |j| if j > i { f32::NEG_INFINITY } else { 0.0 })
                    })
                    .collect();
                let mask = Tensor::from_vec(mask, (1, rows, seq), &Device::Cpu)?;
                candle_nn::ops::softmax_last_dim(&scores.broadcast_add(&mask)?)
            })?;
            parts.push(timed(PROBS_MATMUL, || probs.matmul(&v))?);
        }
        let out = timed(PROBS_MATMUL, || {
            if parts.len() == 1 {
                Ok(parts.remove(0))
            } else {
                Tensor::cat(&parts, 1)
            }
        })?;
        let gated = timed(FULL_OUT_GATE, || {
            out.transpose(0, 1)?.contiguous()?.reshape((seq, 2048))?
                * candle_nn::ops::sigmoid(&gate)?
        })?;
        linear(&gated, weights, &format!("{prefix}.o_proj"))
    }

    /// One head of `delta_recurrence`, written as `out[t * V + j]` (head-major).
    fn delta_head(
        h: usize,
        seq: usize,
        q: &[f32],
        k: &[f32],
        v: &[f32],
        beta: &[f32],
        decay: &[f32],
    ) -> Vec<f32> {
        const COLUMNS: usize = 32;
        let mut out = vec![0_f32; seq * V];
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
                out[t * V + column..][..COLUMNS].copy_from_slice(&output);
            }
        }
        out
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
        let threads = candle_core::utils::get_num_threads();
        if PARALLEL_HEADS.load(Ordering::Relaxed) && threads > 1 {
            // Each thread computes whole heads into its own head-major buffer with exactly the
            // operations and order of the serial loop below; only where the values are written
            // differs, so the result is bitwise the same.
            let (q, k, v, beta, decay) = (&q, &k, &v, &beta, &decay);
            let heads: Vec<(usize, Vec<f32>)> = std::thread::scope(|scope| {
                let workers: Vec<_> = (0..threads.min(H))
                    .map(|w| {
                        scope.spawn(move || {
                            (w..H)
                                .step_by(threads.min(H))
                                .map(|h| (h, delta_head(h, seq, q, k, v, beta, decay)))
                                .collect::<Vec<_>>()
                        })
                    })
                    .collect();
                workers
                    .into_iter()
                    .flat_map(|w| w.join().unwrap())
                    .collect()
            });
            let mut out = vec![0_f32; seq * H * V];
            for (h, head) in heads {
                for t in 0..seq {
                    out[(t * H + h) * V..][..V].copy_from_slice(&head[t * V..][..V]);
                }
            }
            return Tensor::from_vec(out, (seq, H, V), &Device::Cpu);
        }
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
        // Each weight is used before the next one is converted into the shared buffer.
        let dt_bias = weight(weights, &format!("{prefix}.dt_bias"))?;
        let softplus = timed(SOFTPLUS_G, || {
            let a = a.broadcast_add(&dt_bias)?;
            // Stable softplus matches PyTorch's beta=1, threshold=20 behavior.
            let softplus: Vec<f32> = a
                .flatten_all()?
                .to_vec1::<f32>()?
                .iter()
                .map(|&v| if v > 20.0 { v } else { v.exp().ln_1p() })
                .collect();
            Tensor::from_vec(softplus, (seq, H), &Device::Cpu)
        })?;
        let a_log = weight(weights, &format!("{prefix}.A_log"))?;
        let g = timed(SOFTPLUS_G, || softplus.broadcast_mul(&a_log.exp()?.neg()?))?;
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
        BUFFER.with(|b| *b.borrow_mut() = None);
        let seq = ids.len();
        let mut x = timed(EMBEDDING, || {
            weights.load_f32_rows("language_model.embed_tokens.weight", ids)
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
    if let Some(i) = args.iter().position(|a| a == "--parallel-heads") {
        args.remove(i);
        profiled::PARALLEL_HEADS.store(true, std::sync::atomic::Ordering::Relaxed);
    }
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
            // The library forward (no timers) in alternating order, for the timer overhead.
            let library = || -> Result<f64> {
                let step = Instant::now();
                let hidden = backbone::forward(&weights, &prepared.ids)?;
                let elapsed = step.elapsed().as_secs_f64();
                ensure!(
                    bits(&hidden)? == expected,
                    "{path}: library forward not repeatable"
                );
                Ok(elapsed)
            };
            let library_before = if rep % 2 == 0 { Some(library()?) } else { None };
            prof::take();
            let step = Instant::now();
            let hidden = profiled::forward(&weights, &prepared.ids)?;
            let forward_s = step.elapsed().as_secs_f64();
            let seconds = prof::take();
            ensure!(
                bits(&hidden)? == expected,
                "{path}: profiled forward differs"
            );
            let library_s = match library_before {
                Some(s) => s,
                None => library()?,
            };
            let categories: serde_json::Map<_, _> = prof::NAMES
                .iter()
                .zip(&seconds)
                .map(|(name, s)| ((*name).to_owned(), serde_json::json!(s)))
                .collect();
            println!(
                "{}",
                serde_json::json!({"case": Path::new(path).file_stem().unwrap().to_string_lossy(),
                    "parallel_heads": profiled::PARALLEL_HEADS.load(std::sync::atomic::Ordering::Relaxed),
                    "input_tokens": prepared.ids.len(), "rep": rep, "forward_s": forward_s,
                    "library_forward_s": library_s, "timer_overhead": forward_s / library_s - 1.0,
                    "timed_s": seconds.iter().sum::<f64>(), "bitwise_equal": true,
                    "seconds": categories})
            );
        }
    }
    Ok(())
}
