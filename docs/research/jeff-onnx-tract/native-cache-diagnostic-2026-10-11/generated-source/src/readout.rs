use crate::weights::Weights;
use anyhow::{ensure, Result};
use candle_core::{DType, Device, Tensor};
pub fn probabilities(
    weights: &Weights,
    hidden: &Tensor,
    count: usize,
    temperature: f64,
) -> Result<(Vec<f64>, Vec<f32>)> {
    ensure!(
        (2..=255).contains(&count) && temperature.is_finite() && temperature > 0.0,
        "invalid readout request"
    );
    let weight = weights.load("weight", &Device::Cpu)?.to_dtype(DType::F32)?;
    ensure!(
        weight.dims() == [255, 1024] && hidden.dims() == [1, 1024],
        "readout shape mismatch"
    );
    let logits = hidden
        .matmul(&weight.t()?)?
        .flatten_all()?
        .to_vec1::<f32>()?;
    ensure!(logits.iter().all(|x| x.is_finite()), "nonfinite logits");
    let masked: Vec<f32> = logits
        .iter()
        .enumerate()
        .map(|(i, v)| if i < count { *v } else { -1e9 })
        .collect();
    let p = candle_nn::ops::softmax_last_dim(
        &(Tensor::from_vec(masked, (1, 255), &Device::Cpu)? / temperature)?,
    )?
    .flatten_all()?
    .narrow(0, 0, count)?
    .to_vec1::<f32>()?;
    Ok((p.into_iter().map(f64::from).collect(), logits))
}
