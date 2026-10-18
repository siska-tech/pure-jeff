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
    use std::{cell::RefCell, collections::BTreeMap, time::Instant};

    pub const NAMES: [&str; 27] = [
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
        "delta_extract",
        "delta_prep",
        "delta_core",
        "delta_sync",
        "delta_writeback",
    ];

    thread_local! {
        static STATE: RefCell<(Vec<f64>, Vec<f64>)> =
            RefCell::new((vec![0.0; NAMES.len()], Vec::new()));
        // Details that are not part of the forward's time (sums over the forward).
        static NOTES: RefCell<BTreeMap<&'static str, f64>> = const { RefCell::new(BTreeMap::new()) };
    }

    /// Moves `seconds` of category `from` to category `to` (splitting a timed span).
    pub fn shift(from: usize, to: usize, seconds: f64) {
        STATE.with(|s| {
            let mut s = s.borrow_mut();
            s.0[from] -= seconds;
            s.0[to] += seconds;
        });
    }

    pub fn note(name: &'static str, value: f64) {
        NOTES.with(|n| *n.borrow_mut().entry(name).or_insert(0.0) += value);
    }

    pub fn take_notes() -> BTreeMap<&'static str, f64> {
        NOTES.with(|n| std::mem::take(&mut *n.borrow_mut()))
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
    use super::prof::{self, timed};
    use candle_core::{CpuStorage, Device, InplaceOp1, Layout, Result, Storage, Tensor, D};
    use pure_jeff::WeightSource;
    use rayon::prelude::*;
    use std::cell::{Cell, RefCell};
    use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
    use std::sync::Mutex;
    use std::time::Instant;

    /// How `delta_recurrence` runs (`--delta`). Experiments only; the library always runs the
    /// serial loop. Every variant computes each head with the library's operations in the
    /// library's order; only the thread and the place a value is written differ.
    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    pub enum Delta {
        /// The library loop.
        Serial,
        /// The 2026-10-18 experiment (`--parallel-heads`): whole heads on newly spawned scoped
        /// threads, each into its own buffer; preparation and the copy back stay serial.
        Scoped,
        /// As `Scoped`, but on the existing rayon pool that Candle and gemm use.
        Pool,
        /// Heads on the rayon pool, each reading q, k, v, beta and g in place and doing its own
        /// q scaling and exp; the copy back runs on the pool by token ranges.
        Fused,
    }

    impl Delta {
        pub const ALL: [Delta; 4] = [Delta::Serial, Delta::Scoped, Delta::Pool, Delta::Fused];

        pub fn name(self) -> &'static str {
            match self {
                Delta::Serial => "serial",
                Delta::Scoped => "scoped",
                Delta::Pool => "pool",
                Delta::Fused => "fused",
            }
        }
    }

    static DELTA: AtomicU8 = AtomicU8::new(0);
    /// Off (`--no-stage-timers`): `delta_recurrence` is timed as one span, for the timers' cost.
    pub static STAGE_TIMERS: AtomicBool = AtomicBool::new(true);
    /// The inputs of the first `delta_recurrence` call after `capture_next` (for the probe).
    static CAPTURE: Mutex<Option<Option<Captured>>> = Mutex::new(None);

    pub struct Captured {
        pub seq: usize,
        pub q: Vec<f32>,
        pub k: Vec<f32>,
        pub v: Vec<f32>,
        pub beta: Vec<f32>,
        pub g: Vec<f32>,
    }

    pub fn set_delta(delta: Delta) {
        DELTA.store(delta as u8, Ordering::Relaxed);
    }

    pub fn delta() -> Delta {
        Delta::ALL[DELTA.load(Ordering::Relaxed) as usize]
    }

    pub fn capture_next() {
        *CAPTURE.lock().unwrap() = Some(None);
    }

    pub fn take_capture() -> Option<Captured> {
        CAPTURE.lock().unwrap().take().flatten()
    }

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
    const DELTA_EXTRACT: usize = 22;
    const DELTA_PREP: usize = 23;
    const DELTA_CORE: usize = 24;
    const DELTA_SYNC: usize = 25;
    const DELTA_WRITEBACK: usize = 26;

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

    const COLUMNS: usize = 32;

    /// `timed` for a stage of `delta_recurrence`, or untimed with `--no-stage-timers`.
    fn stage<R>(cat: usize, f: impl FnOnce() -> R) -> R {
        if STAGE_TIMERS.load(Ordering::Relaxed) {
            timed(cat, f)
        } else {
            f()
        }
    }

    /// Columns `column..column + COLUMNS` of head `h` for every token: the body of the library
    /// loop, unchanged. With `RAW`, `q` is not yet divided by sqrt(K) and `d` holds g, not
    /// exp(g); each value is then divided / exponentiated here with the same operation the
    /// library's preparation uses, so every value the loop sees is the same. `write(t, out)`
    /// stores token t's output columns.
    #[inline(always)]
    #[allow(clippy::too_many_arguments)]
    pub fn head_columns<const RAW: bool>(
        h: usize,
        column: usize,
        seq: usize,
        q: &[f32],
        k: &[f32],
        v: &[f32],
        beta: &[f32],
        d: &[f32],
        mut write: impl FnMut(usize, &[f32; COLUMNS]),
    ) {
        let scale = (K as f32).sqrt();
        let mut state = [[0_f32; COLUMNS]; K];
        let mut scaled = [0_f32; K];
        for t in 0..seq {
            let at = t * H + h;
            let (q, k) = (&q[at * K..][..K], &k[at * K..][..K]);
            let q: &[f32] = if RAW {
                for (s, x) in scaled.iter_mut().zip(q) {
                    *s = x / scale;
                }
                &scaled
            } else {
                q
            };
            let decay = if RAW { d[at].exp() } else { d[at] };
            let mut delta = [0_f32; COLUMNS];
            for (row, ki) in state.iter_mut().zip(k) {
                for (s, d) in row.iter_mut().zip(&mut delta) {
                    *s *= decay;
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
            write(t, &output);
        }
    }

    /// One whole head into `out` (seq x V, head-major).
    #[allow(clippy::too_many_arguments)]
    pub fn head<const RAW: bool>(
        h: usize,
        seq: usize,
        q: &[f32],
        k: &[f32],
        v: &[f32],
        beta: &[f32],
        d: &[f32],
        out: &mut [f32],
    ) {
        for column in (0..V).step_by(COLUMNS) {
            head_columns::<RAW>(h, column, seq, q, k, v, beta, d, |t, o| {
                out[t * V + column..][..COLUMNS].copy_from_slice(o)
            });
        }
    }

    /// When and on which thread one task of a parallel region ran (seconds from its start).
    #[derive(Clone, Copy)]
    struct Span {
        thread: usize,
        start: f64,
        end: f64,
    }

    /// Splits a region's wall time: the busiest thread's work stays `delta_core`, the rest of
    /// the wall (spawn or wake, waiting, join) moves to `delta_sync`. Notes the imbalance and
    /// how late the threads started.
    fn account(wall: f64, spans: &[Span]) {
        let mut busy = std::collections::BTreeMap::<usize, (f64, f64)>::new();
        for s in spans {
            let entry = busy.entry(s.thread).or_insert((0.0, f64::INFINITY));
            entry.0 += s.end - s.start;
            entry.1 = entry.1.min(s.start);
        }
        let max = busy.values().map(|b| b.0).fold(0.0, f64::max);
        let sum: f64 = busy.values().map(|b| b.0).sum();
        if STAGE_TIMERS.load(Ordering::Relaxed) {
            prof::shift(DELTA_CORE, DELTA_SYNC, (wall - max).max(0.0));
        }
        prof::note("region_wall", wall);
        prof::note("busiest_thread", max);
        prof::note("imbalance", max - sum / busy.len() as f64);
        prof::note("busy_sum", sum);
        prof::note(
            "first_start",
            busy.values().map(|b| b.1).fold(f64::INFINITY, f64::min),
        );
        prof::note(
            "last_first_start",
            busy.values().map(|b| b.1).fold(0.0, f64::max),
        );
        prof::note("threads_used", busy.len() as f64);
        prof::note("regions", 1.0);
    }

    /// The tensor's f32 elements in place; the tensor must be contiguous.
    fn contiguous_f32<'a>(storage: &'a Storage, layout: &Layout) -> Result<&'a [f32]> {
        match (storage, layout.contiguous_offsets()) {
            (Storage::Cpu(CpuStorage::F32(data)), Some((start, end))) => Ok(&data[start..end]),
            _ => candle_core::bail!("expected a contiguous f32 tensor"),
        }
    }

    // Copy of src/backbone.rs's delta_recurrence (column-blocked, bitwise equal to the
    // reference), split into stages, with the experimental variants of `Delta`.
    fn delta_recurrence(
        q: &Tensor,
        k: &Tensor,
        v: &Tensor,
        beta: &Tensor,
        g: &Tensor,
    ) -> Result<Tensor> {
        let seq = q.dim(0)?;
        {
            let mut capture = CAPTURE.lock().unwrap();
            if let Some(None) = *capture {
                *capture = Some(Some(Captured {
                    seq,
                    q: q.flatten_all()?.to_vec1()?,
                    k: k.flatten_all()?.to_vec1()?,
                    v: v.flatten_all()?.to_vec1()?,
                    beta: beta.flatten_all()?.to_vec1()?,
                    g: g.flatten_all()?.to_vec1()?,
                }));
            }
        }
        let variant = delta();
        if variant == Delta::Fused {
            return delta_fused(seq, q, k, v, beta, g);
        }
        let scale = (K as f32).sqrt();
        let (q, k, v, beta, g) = stage(DELTA_EXTRACT, || -> Result<_> {
            Ok((
                q.flatten_all()?.to_vec1::<f32>()?,
                k.flatten_all()?.to_vec1::<f32>()?,
                v.flatten_all()?.to_vec1::<f32>()?,
                beta.flatten_all()?.to_vec1::<f32>()?,
                g.flatten_all()?.to_vec1::<f32>()?,
            ))
        })?;
        let (q, decay) = stage(DELTA_PREP, || {
            let q: Vec<f32> = q.iter().map(|x| x / scale).collect();
            let decay: Vec<f32> = g.iter().map(|g| g.exp()).collect();
            (q, decay)
        });
        let (q, k, v, beta, decay) = (&q[..], &k[..], &v[..], &beta[..], &decay[..]);
        if variant == Delta::Serial {
            let out = stage(DELTA_CORE, || {
                let mut out = vec![0_f32; seq * H * V];
                for h in 0..H {
                    for column in (0..V).step_by(COLUMNS) {
                        head_columns::<false>(h, column, seq, q, k, v, beta, decay, |t, o| {
                            out[(t * H + h) * V + column..][..COLUMNS].copy_from_slice(o)
                        });
                    }
                }
                out
            });
            return stage(DELTA_WRITEBACK, || {
                Tensor::from_vec(out, (seq, H, V), &Device::Cpu)
            });
        }
        let one = |h: usize, thread: usize, begin: Instant| {
            let start = begin.elapsed().as_secs_f64();
            let mut out = vec![0_f32; seq * V];
            head::<false>(h, seq, q, k, v, beta, decay, &mut out);
            let span = Span {
                thread,
                start,
                end: begin.elapsed().as_secs_f64(),
            };
            (h, out, span)
        };
        let heads: Vec<(usize, Vec<f32>, Span)> = stage(DELTA_CORE, || {
            let begin = Instant::now();
            let heads: Vec<_> = if variant == Delta::Scoped {
                let threads = candle_core::utils::get_num_threads().min(H);
                std::thread::scope(|scope| {
                    let workers: Vec<_> = (0..threads)
                        .map(|w| {
                            scope.spawn(move || {
                                (w..H)
                                    .step_by(threads)
                                    .map(|h| one(h, w, begin))
                                    .collect::<Vec<_>>()
                            })
                        })
                        .collect();
                    workers
                        .into_iter()
                        .flat_map(|w| w.join().unwrap())
                        .collect()
                })
            } else {
                (0..H)
                    .into_par_iter()
                    .map(|h| {
                        one(
                            h,
                            rayon::current_thread_index().unwrap_or(usize::MAX),
                            begin,
                        )
                    })
                    .collect()
            };
            let wall = begin.elapsed().as_secs_f64();
            let spans: Vec<Span> = heads.iter().map(|(_, _, s)| *s).collect();
            account(wall, &spans);
            heads
        });
        stage(DELTA_WRITEBACK, || {
            let mut out = vec![0_f32; seq * H * V];
            for (h, head, _) in heads {
                for t in 0..seq {
                    out[(t * H + h) * V..][..V].copy_from_slice(&head[t * V..][..V]);
                }
            }
            Tensor::from_vec(out, (seq, H, V), &Device::Cpu)
        })
    }

    /// `Delta::Fused`: no extraction or preparation pass; each head task reads the tensors in
    /// place (`head::<true>`), and the copy back to (seq, H, V) runs on the pool by tokens.
    fn delta_fused(
        seq: usize,
        q: &Tensor,
        k: &Tensor,
        v: &Tensor,
        beta: &Tensor,
        g: &Tensor,
    ) -> Result<Tensor> {
        let (q, k, v, beta, g) = stage(DELTA_EXTRACT, || -> Result<_> {
            Ok((
                q.contiguous()?,
                k.contiguous()?,
                v.contiguous()?,
                beta.contiguous()?,
                g.contiguous()?,
            ))
        })?;
        let guards = [&q, &k, &v, &beta, &g].map(|t| t.storage_and_layout());
        let slices: Vec<&[f32]> = guards
            .iter()
            .map(|(storage, layout)| contiguous_f32(storage, layout))
            .collect::<Result<_>>()?;
        let [q, k, v, beta, g] = slices[..] else {
            unreachable!()
        };
        let heads: Vec<Vec<f32>> = stage(DELTA_CORE, || {
            let begin = Instant::now();
            let heads: Vec<(Vec<f32>, Span)> = (0..H)
                .into_par_iter()
                .map(|h| {
                    let start = begin.elapsed().as_secs_f64();
                    let mut out = vec![0_f32; seq * V];
                    head::<true>(h, seq, q, k, v, beta, g, &mut out);
                    let span = Span {
                        thread: rayon::current_thread_index().unwrap_or(usize::MAX),
                        start,
                        end: begin.elapsed().as_secs_f64(),
                    };
                    (out, span)
                })
                .collect();
            let wall = begin.elapsed().as_secs_f64();
            let (heads, spans): (Vec<_>, Vec<_>) = heads.into_iter().unzip();
            account(wall, &spans);
            heads
        });
        stage(DELTA_WRITEBACK, || {
            let mut out = vec![0_f32; seq * H * V];
            out.par_chunks_mut(H * V)
                .with_min_len(16)
                .enumerate()
                .for_each(|(t, row)| {
                    for (h, o) in row.chunks_exact_mut(V).enumerate() {
                        o.copy_from_slice(&heads[h][t * V..][..V]);
                    }
                });
            Tensor::from_vec(out, (seq, H, V), &Device::Cpu)
        })
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

/// Removes `flag` and its value from `args`.
fn take_value(args: &mut Vec<String>, flag: &str) -> Option<String> {
    let i = args.iter().position(|a| a == flag)?;
    let value = args.remove(i + 1);
    args.remove(i);
    Some(value)
}

/// Removes `flag` from `args`; true when it was there.
fn take_flag(args: &mut Vec<String>, flag: &str) -> bool {
    match args.iter().position(|a| a == flag) {
        Some(i) => {
            args.remove(i);
            true
        }
        None => false,
    }
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    values[values.len() / 2]
}

/// The logical CPU running this thread (diagnostic only; the OS may move the thread anytime).
#[cfg(windows)]
fn current_cpu() -> Option<u32> {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcessorNumber() -> u32;
    }
    // SAFETY: no arguments; returns the number of the processor running this thread.
    Some(unsafe { GetCurrentProcessorNumber() })
}

#[cfg(not(windows))]
fn current_cpu() -> Option<u32> {
    None
}

/// What `concurrent` saw: the median over reps of the mean and of the slowest thread's
/// seconds, and where the threads ran when they finished (logical CPU numbers; on this machine
/// 2c and 2c + 1 are the two threads of core c, as Windows numbers AMD SMT siblings).
struct Concurrent {
    mean: f64,
    max: f64,
    /// Median over reps of the threads that finished sharing a core with another of them.
    sharing_core: f64,
}

/// Runs `work(i)` on `n` new threads that start together, `reps` times.
fn concurrent(n: usize, reps: usize, work: &(dyn Fn(usize) + Sync)) -> Concurrent {
    let (mut means, mut maxes, mut sharing) = (Vec::new(), Vec::new(), Vec::new());
    for _ in 0..reps {
        let barrier = std::sync::Barrier::new(n);
        let runs: Vec<(f64, Option<u32>)> = std::thread::scope(|scope| {
            let workers: Vec<_> = (0..n)
                .map(|i| {
                    let barrier = &barrier;
                    scope.spawn(move || {
                        barrier.wait();
                        let start = Instant::now();
                        work(i);
                        (start.elapsed().as_secs_f64(), current_cpu())
                    })
                })
                .collect();
            workers.into_iter().map(|w| w.join().unwrap()).collect()
        });
        means.push(runs.iter().map(|r| r.0).sum::<f64>() / n as f64);
        maxes.push(runs.iter().map(|r| r.0).fold(0.0, f64::max));
        let cores: Vec<u32> = runs.iter().filter_map(|r| r.1.map(|c| c / 2)).collect();
        sharing.push(
            cores
                .iter()
                .filter(|c| cores.iter().filter(|d| d == c).count() > 1)
                .count() as f64,
        );
    }
    Concurrent {
        mean: median(means),
        max: median(maxes),
        sharing_core: median(sharing),
    }
}

/// Shared-resource probe on one layer's real inputs: n threads each compute one different head
/// at the same time (weak scaling). If a head takes longer as n grows, something shared slows
/// it (memory bandwidth, the shared L3, the clock under load, two threads on one core).
/// "resident" runs the first 64 tokens over and over (one head's rows fit in L2), so memory
/// is out of the picture; "copy" is a plain memory copy for the machine's bandwidth.
fn probe_scaling(c: &profiled::Captured) -> serde_json::Value {
    const H: usize = 16;
    const V: usize = 128;
    let scale = (128_f32).sqrt();
    let q: Vec<f32> = c.q.iter().map(|x| x / scale).collect();
    let decay: Vec<f32> = c.g.iter().map(|g| g.exp()).collect();
    // Each task covers at least 8192 tokens of work (a few tens of ms), so thread start and
    // clock ramp-up are small against it.
    let resident = c.seq.min(64);
    let repeats = 8192_usize.div_ceil(resident);
    let full_repeats = 8192_usize.div_ceil(c.seq);
    let reps = 5;
    let mut rows = Vec::new();
    for n in [1, 2, 4, 8, 16] {
        let full = |i: usize| {
            let mut out = vec![0_f32; c.seq * V];
            for _ in 0..full_repeats {
                profiled::head::<false>(i % H, c.seq, &q, &c.k, &c.v, &c.beta, &decay, &mut out);
                std::hint::black_box(&out);
            }
        };
        let l2 = |i: usize| {
            let mut out = vec![0_f32; resident * V];
            for _ in 0..repeats {
                profiled::head::<false>(i % H, resident, &q, &c.k, &c.v, &c.beta, &decay, &mut out);
                std::hint::black_box(&out);
            }
        };
        const COPY: usize = 8 << 20; // 32 MiB of f32 per thread
        let sources: Vec<Vec<f32>> = (0..n).map(|i| vec![i as f32; COPY]).collect();
        let targets: Vec<std::sync::Mutex<Vec<f32>>> = (0..n)
            .map(|_| std::sync::Mutex::new(vec![1.0; COPY]))
            .collect();
        let copy = |i: usize| {
            let mut target = targets[i].lock().unwrap();
            for _ in 0..4 {
                target.copy_from_slice(&sources[i]);
                std::hint::black_box(&*target);
            }
        };
        let full = concurrent(n, reps, &full);
        let l2 = concurrent(n, reps, &l2);
        let copy = concurrent(n, reps, &copy);
        rows.push(
            serde_json::json!({"threads": n, "head_full_mean_s": full.mean,
            "head_full_max_s": full.max, "head_full_sharing_core": full.sharing_core,
            "head_resident_mean_s": l2.mean, "head_resident_max_s": l2.max,
            "head_resident_sharing_core": l2.sharing_core,
            "copy_gb_per_s": (n * COPY * 4 * 2 * 4) as f64 / copy.max / 1e9}),
        );
    }
    serde_json::json!({"probe": "scaling", "seq": c.seq, "resident_tokens": resident,
        "resident_repeats": repeats, "full_repeats": full_repeats, "reps": reps, "rows": rows})
}

fn main() -> Result<()> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut variants = Vec::new();
    if take_flag(&mut args, "--parallel-heads") {
        variants.push(profiled::Delta::Scoped);
    }
    if let Some(list) = take_value(&mut args, "--delta") {
        for name in list.split(',') {
            variants.push(
                *profiled::Delta::ALL
                    .iter()
                    .find(|d| d.name() == name)
                    .with_context(|| format!("unknown --delta {name}"))?,
            );
        }
    }
    if variants.is_empty() {
        variants.push(profiled::Delta::Serial);
    }
    if take_flag(&mut args, "--no-stage-timers") {
        profiled::STAGE_TIMERS.store(false, std::sync::atomic::Ordering::Relaxed);
    }
    let probe = take_flag(&mut args, "--probe-scaling");
    let reps = match take_value(&mut args, "--reps") {
        Some(value) => value.parse()?,
        None => 3,
    };
    let (manifest, cases) = args.split_first().context(
        "usage: forward_breakdown <manifest> <golden.json>... [--reps N] \
         [--delta serial,scoped,pool,fused] [--no-stage-timers] [--probe-scaling]",
    )?;
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
    ensure!(
        rayon::current_num_threads() == bundle.manifest.policy.cpu_threads,
        "the rayon pool differs from the bundle policy"
    );
    let bits = |t: &candle_core::Tensor| -> Result<Vec<u32>> {
        Ok(t.flatten_all()?
            .to_vec1::<f32>()?
            .iter()
            .map(|v| v.to_bits())
            .collect())
    };
    // For comparing final hidden states across processes and thread counts.
    let digest = |bits: &[u32]| -> String {
        use sha2::Digest;
        let mut hash = sha2::Sha256::new();
        for b in bits {
            hash.update(b.to_le_bytes());
        }
        format!("{:x}", hash.finalize())
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
        let hidden_sha256 = digest(&expected);
        if probe {
            profiled::capture_next();
        }
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
            // Each rep runs every variant, starting one further along the list each time.
            let mut timings = Vec::new();
            for i in 0..variants.len() {
                let variant = variants[(rep + i) % variants.len()];
                profiled::set_delta(variant);
                prof::take();
                prof::take_notes();
                let step = Instant::now();
                let hidden = profiled::forward(&weights, &prepared.ids)?;
                let forward_s = step.elapsed().as_secs_f64();
                let seconds = prof::take();
                let notes = prof::take_notes();
                ensure!(
                    bits(&hidden)? == expected,
                    "{path}: profiled forward ({}) differs",
                    variant.name()
                );
                timings.push((variant, forward_s, seconds, notes));
            }
            let library_s = match library_before {
                Some(s) => s,
                None => library()?,
            };
            for (order, (variant, forward_s, seconds, notes)) in timings.into_iter().enumerate() {
                let categories: serde_json::Map<_, _> = prof::NAMES
                    .iter()
                    .zip(&seconds)
                    .map(|(name, s)| ((*name).to_owned(), serde_json::json!(s)))
                    .collect();
                println!(
                    "{}",
                    serde_json::json!({"case": Path::new(path).file_stem().unwrap().to_string_lossy(),
                        "delta": variant.name(), "order": order,
                        "parallel_heads": variant != profiled::Delta::Serial,
                        "stage_timers": profiled::STAGE_TIMERS.load(std::sync::atomic::Ordering::Relaxed),
                        "threads": bundle.manifest.policy.cpu_threads,
                        "input_tokens": prepared.ids.len(), "rep": rep, "forward_s": forward_s,
                        "library_forward_s": library_s, "timer_overhead": forward_s / library_s - 1.0,
                        "timed_s": seconds.iter().sum::<f64>(), "bitwise_equal": true,
                        "hidden_sha256": hidden_sha256,
                        "seconds": categories, "delta_notes": notes})
                );
            }
        }
        if let Some(captured) = profiled::take_capture() {
            let mut row = probe_scaling(&captured);
            row["case"] = serde_json::json!(Path::new(path).file_stem().unwrap().to_string_lossy());
            println!("{row}");
        }
    }
    Ok(())
}
