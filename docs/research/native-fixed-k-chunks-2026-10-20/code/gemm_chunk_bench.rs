//! Experiment (#18): the cost of splitting k into chunks of at most 512, three ways, on the
//! forward's linear shapes: Candle's matmul as is; the chunks through Candle, added with `+`
//! (one new tensor per chunk and per sum); and the chunks through gemm directly, the later ones
//! accumulated into the same output (`read_dst`). Prints the median time of each and whether the
//! two chunked results are bitwise equal.
//!
//!   gemm_chunk_bench <threads> <seq> [repeats]
use anyhow::{ensure, Context, Result};
use candle_core::{Device, Tensor};
use serde_json::json;
use std::time::Instant;

fn uniform(seed: &mut u64, n: usize) -> Vec<f32> {
    (0..n)
        .map(|_| {
            *seed ^= *seed << 13;
            *seed ^= *seed >> 7;
            *seed ^= *seed << 17;
            ((*seed >> 40) as f32 / (1u64 << 24) as f32) * 2.0 - 1.0
        })
        .collect()
}

fn chunks(k: usize) -> Vec<(usize, usize)> {
    let chunk = k.div_ceil(k.div_ceil(512));
    (0..k)
        .step_by(chunk)
        .map(|s| (s, chunk.min(k - s)))
        .collect()
}

/// x (m, k) row-major, w (n, k) row-major: x w^T, k in chunks, Candle ops only.
fn candle_chunked(x: &Tensor, w: &Tensor) -> Result<Tensor> {
    let wt = w.t()?;
    let mut sum: Option<Tensor> = None;
    for (start, size) in chunks(x.dim(1)?) {
        let part = x
            .narrow(1, start, size)?
            .matmul(&wt.narrow(0, start, size)?)?;
        sum = Some(match sum {
            Some(s) => (s + part)?,
            None => part,
        });
    }
    sum.context("k = 0")
}

/// The same product with gemm called as Candle calls it, the later chunks accumulated.
fn direct_chunked(x: &[f32], w: &[f32], m: usize, n: usize, k: usize, threads: usize) -> Vec<f32> {
    let mut dst = vec![0f32; m * n];
    let parallelism = if threads > 1 {
        gemm::Parallelism::Rayon(threads)
    } else {
        gemm::Parallelism::None
    };
    for (i, (start, size)) in chunks(k).into_iter().enumerate() {
        // SAFETY: dst is m x n row-major; x is m x k (row stride k), w^T is k x n read from the
        // n x k row-major w (column stride k); every index stays inside the three buffers.
        unsafe {
            gemm::gemm(
                m,
                n,
                size,
                dst.as_mut_ptr(),
                1,
                n as isize,
                i > 0,
                x.as_ptr().add(start),
                1,
                k as isize,
                w.as_ptr().add(start),
                k as isize,
                1,
                if i > 0 { 1.0 } else { 0.0 },
                1.0,
                false,
                false,
                false,
                parallelism,
            )
        }
    }
    dst
}

fn median(mut v: Vec<f64>) -> f64 {
    v.sort_by(f64::total_cmp);
    v[v.len() / 2]
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let threads: usize = args.first().context("threads")?.parse()?;
    let m: usize = args.get(1).context("seq")?.parse()?;
    let repeats: usize = args.get(2).map(|r| r.parse()).transpose()?.unwrap_or(5);
    pure_jeff::configure_threads(threads)?;
    let mut seed = 0x5eed_u64;
    for (name, n, k) in [
        ("q_proj", 4096, 1024),
        ("gate/up_proj", 3584, 1024),
        ("out_proj", 1024, 2048),
        ("down_proj", 1024, 3584),
    ] {
        let xv = uniform(&mut seed, m * k);
        let wv = uniform(&mut seed, n * k);
        let x = Tensor::from_vec(xv.clone(), (m, k), &Device::Cpu)?;
        let w = Tensor::from_vec(wv.clone(), (n, k), &Device::Cpu)?;
        let (mut plain, mut candle, mut direct) = (Vec::new(), Vec::new(), Vec::new());
        let mut equal = true;
        for _ in 0..repeats {
            let t = Instant::now();
            let p = x.matmul(&w.t()?)?;
            plain.push(t.elapsed().as_secs_f64());
            drop(p);
            let t = Instant::now();
            let c = candle_chunked(&x, &w)?;
            candle.push(t.elapsed().as_secs_f64());
            let t = Instant::now();
            let d = direct_chunked(&xv, &wv, m, n, k, threads);
            direct.push(t.elapsed().as_secs_f64());
            let c: Vec<f32> = c.flatten_all()?.to_vec1()?;
            equal &= c.iter().zip(&d).all(|(a, b)| a.to_bits() == b.to_bits());
        }
        ensure!(equal, "{name}: direct and Candle chunks differ");
        println!(
            "{}",
            json!({"name": name, "m": m, "n": n, "k": k, "threads": threads,
            "plain_s": median(plain), "candle_chunked_s": median(candle), "direct_chunked_s": median(direct),
            "bitwise_equal": equal})
        );
    }
    Ok(())
}
