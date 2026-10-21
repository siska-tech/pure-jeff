//! Diagnostic (#18): the element-wise functions of the forward on fixed inputs, one SHA-256 of
//! the output bits per function. Equal digests on two hosts mean the platform math gives the same
//! bits there (Rust's f32 exp, ln_1p and powf call the system's math library).
use anyhow::Result;
use candle_core::{Device, Tensor};
use serde_json::json;
use sha2::{Digest, Sha256};

fn digest(v: &[f32]) -> String {
    let bytes: Vec<u8> = v.iter().flat_map(|x| x.to_bits().to_le_bytes()).collect();
    format!("{:x}", Sha256::digest(&bytes))
}

fn main() -> Result<()> {
    let mut seed = 0x5eed_u64;
    let x: Vec<f32> = (0..1 << 20)
        .map(|_| {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            ((seed >> 40) as f32 / (1u64 << 24) as f32) * 40.0 - 20.0
        })
        .collect();
    let t = Tensor::from_vec(x.clone(), (1024, 1024), &Device::Cpu)?;
    let map = |f: fn(f32) -> f32| x.iter().map(|&v| f(v)).collect::<Vec<_>>();
    let pow: Vec<f32> = (0..64)
        .map(|j| 1.0 / 10_000_000_f32.powf((2 * j) as f32 / 64.0))
        .collect();
    let rows = [
        ("exp", digest(&map(f32::exp))),
        ("ln_1p(exp)", digest(&map(|v| v.exp().ln_1p()))),
        ("silu", digest(&map(|v| v / (1.0 + (-v).exp())))),
        ("sqrt(|x|)", digest(&map(|v| v.abs().sqrt()))),
        ("powf (rotary)", digest(&pow)),
        ("candle exp", digest(&t.exp()?.flatten_all()?.to_vec1()?)),
        (
            "candle sigmoid",
            digest(&candle_nn::ops::sigmoid(&t)?.flatten_all()?.to_vec1()?),
        ),
        (
            "candle softmax",
            digest(
                &candle_nn::ops::softmax_last_dim(&t)?
                    .flatten_all()?
                    .to_vec1()?,
            ),
        ),
        (
            "candle sum",
            digest(&t.sum_keepdim(1)?.flatten_all()?.to_vec1()?),
        ),
    ];
    for (name, d) in rows {
        println!("{}", json!({"function": name, "sha256": d}));
    }
    Ok(())
}
