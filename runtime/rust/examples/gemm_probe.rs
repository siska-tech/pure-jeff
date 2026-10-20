//! Diagnostic (#18): the F32 matrix products of the forward, with the forward's shapes and
//! layouts, on fixed data; one SHA-256 of the output bits per product. Run it in processes that
//! start on different CPUs (or hosts) and compare: equal digests mean gemm summed in the same
//! order there. Each product is also computed with k split into chunks of at most 512 (see
//! below). The gemm CACHE_INFO of this process is printed first.
//!
//!   gemm_probe <threads> [seq...]      (default seq: 128 513 874)
use anyhow::{Context, Result};
use candle_core::{Device, Tensor, D};
use serde_json::json;
use sha2::{Digest, Sha256};
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

fn digest(t: &Tensor) -> Result<String> {
    let bytes: Vec<u8> = t
        .flatten_all()?
        .to_vec1::<f32>()?
        .iter()
        .flat_map(|v| v.to_bits().to_le_bytes())
        .collect();
    Ok(format!("{:x}", Sha256::digest(&bytes)))
}

fn tensor(seed: &mut u64, shape: &[usize]) -> Result<Tensor> {
    let n = shape.iter().product();
    Ok(Tensor::from_vec(uniform(seed, n), shape, &Device::Cpu)?)
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let threads: usize = args
        .first()
        .context("usage: gemm_probe <threads> [seq...]")?
        .parse()?;
    let seqs: Vec<usize> = if args.len() > 1 {
        args[1..]
            .iter()
            .map(|s| s.parse())
            .collect::<Result<_, _>>()?
    } else {
        vec![128, 513, 874]
    };
    pure_jeff::configure_threads(threads)?;
    let caches: Vec<_> = gemm_common::cache::CACHE_INFO
        .iter()
        .map(|c| json!({"bytes": c.cache_bytes, "associativity": c.associativity, "line_bytes": c.cache_line_bytes}))
        .collect();
    println!(
        "{}",
        json!({"event": "init", "threads": candle_core::utils::get_num_threads(), "gemm_cache_info": caches})
    );
    // (name, out, in) of every linear in the forward; `linear` is x.matmul(&w.t()).
    let linears = [
        ("in_proj_a/b", 16, 1024),
        ("k_proj/v_proj", 512, 1024),
        ("in_proj_z", 2048, 1024),
        ("q_proj", 4096, 1024),
        ("in_proj_qkv", 6144, 1024),
        ("gate/up_proj", 3584, 1024),
        ("out_proj/o_proj", 1024, 2048),
        ("down_proj", 1024, 3584),
    ];
    let mut seed = 0x5eed_u64;
    // Every product twice: as the forward computes it, and with k split by this program into
    // the chunks gemm itself uses when kc is at its floor of 512 (ceil(k / 512) chunks of equal
    // size), summed in order. Chunks of at most 512 make gemm's kc equal to the chunk on every
    // host, so the chunked digest should not depend on the CPU the process started on.
    let emit = |name: &str, a: &Tensor, b: &Tensor| -> Result<()> {
        let (m, k) = (a.dim(D::Minus2)?, a.dim(D::Minus1)?);
        let n = b.dim(D::Minus1)?;
        let started = Instant::now();
        let plain = a.matmul(b)?;
        let plain_s = started.elapsed().as_secs_f64();
        let chunk = k.div_ceil(k.div_ceil(512));
        let started = Instant::now();
        let mut chunked: Option<Tensor> = None;
        for start in (0..k).step_by(chunk) {
            let size = chunk.min(k - start);
            let part =
                a.narrow(D::Minus1, start, size)?
                    .matmul(&b.narrow(D::Minus2, start, size)?)?;
            chunked = Some(match chunked {
                Some(sum) => (sum + part)?,
                None => part,
            });
        }
        let chunked_s = started.elapsed().as_secs_f64();
        let chunked = chunked.context("k = 0")?;
        println!(
            "{}",
            json!({"event": "product", "name": name, "m": m, "n": n, "k": k, "chunk": chunk,
                "sha256": digest(&plain)?, "sha256_chunked": digest(&chunked)?,
                "plain_s": plain_s, "chunked_s": chunked_s})
        );
        Ok(())
    };
    for &seq in &seqs {
        for (name, out, inp) in linears {
            let x = tensor(&mut seed, &[seq, inp])?;
            let w = tensor(&mut seed, &[out, inp])?;
            emit(name, &x, &w.t()?)?;
        }
        // Full attention, one block of up to 512 query rows against all keys (8 heads).
        let rows = seq.min(512);
        let q = tensor(&mut seed, &[8, rows, 256])?;
        let kt = tensor(&mut seed, &[8, 256, seq])?;
        emit("attention scores", &q, &kt)?;
        let p = tensor(&mut seed, &[8, rows, seq])?;
        let v = tensor(&mut seed, &[8, seq, 256])?;
        emit("attention values", &p, &v)?;
    }
    let hidden = tensor(&mut seed, &[1, 1024])?;
    let readout = tensor(&mut seed, &[255, 1024])?;
    emit("readout", &hidden, &readout.t()?)?;
    Ok(())
}
