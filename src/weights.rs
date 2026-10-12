use candle_core::{
    safetensors::{MmapedSafetensors, SliceSafetensors},
    DType, Device, Result, Tensor,
};
use half::bf16;

/// Named tensors of a checkpoint: memory-mapped files (Native) or bytes held in memory
/// (browser). The backbone and readout read their weights only through this trait.
pub trait WeightSource {
    fn load(&self, name: &str, device: &Device) -> Result<Tensor>;

    /// The named tensor converted to F32 on the CPU.
    ///
    /// The default loads it and converts it with Candle. An implementation may convert straight
    /// from its bytes, but must give bitwise the same values.
    fn load_f32(&self, name: &str) -> Result<Tensor> {
        self.load(name, &Device::Cpu)?.to_dtype(DType::F32)
    }

    /// Rows `ids` (in that order) of the named 2-D tensor, converted to F32 on the CPU.
    ///
    /// The default loads the whole tensor, selects the rows and converts them with Candle. An
    /// implementation may read only those rows, but must give bitwise the same values.
    fn load_f32_rows(&self, name: &str, ids: &[u32]) -> Result<Tensor> {
        let ids = Tensor::new(ids, &Device::Cpu)?;
        self.load(name, &Device::Cpu)?
            .index_select(&ids, 0)?
            .to_dtype(DType::F32)
    }
}

/// F32 values of a little-endian BF16 safetensors tensor (all rows, or rows `ids`), converted
/// with the same `bf16::to_f32` as Candle's `to_dtype`, without first copying the BF16 bytes.
fn bf16_to_f32(shape: &[usize], data: &[u8], ids: Option<&[u32]>) -> Result<Tensor> {
    if data.len() != 2 * shape.iter().product::<usize>() {
        candle_core::bail!("BF16 tensor of shape {shape:?} has {} bytes", data.len())
    }
    let convert = |bytes: &[u8], out: &mut Vec<f32>| {
        out.extend(
            bytes
                .as_chunks::<2>()
                .0
                .iter()
                .map(|&b| bf16::from_le_bytes(b).to_f32()),
        )
    };
    let mut out = Vec::new();
    let Some(ids) = ids else {
        out.reserve_exact(data.len() / 2);
        convert(data, &mut out);
        return Tensor::from_vec(out, shape, &Device::Cpu);
    };
    let &[rows, columns] = shape else {
        candle_core::bail!("row selection needs a 2-D tensor, not {shape:?}")
    };
    out.reserve_exact(ids.len() * columns);
    for &id in ids {
        let id = id as usize;
        if id >= rows {
            candle_core::bail!("row {id} out of range for {rows} rows")
        }
        convert(&data[id * columns * 2..][..columns * 2], &mut out);
    }
    Tensor::from_vec(out, (ids.len(), columns), &Device::Cpu)
}

// Both safetensors sources convert BF16 tensors straight from their bytes; other dtypes go
// through the default (Candle) path.
macro_rules! direct_bf16 {
    ($source:ty) => {
        impl WeightSource for $source {
            fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
                <$source>::load(self, name, device)
            }

            fn load_f32(&self, name: &str) -> Result<Tensor> {
                let view = self.get(name)?;
                match DType::try_from(view.dtype()) {
                    Ok(DType::BF16) => bf16_to_f32(view.shape(), view.data(), None),
                    _ => self.load(name, &Device::Cpu)?.to_dtype(DType::F32),
                }
            }

            fn load_f32_rows(&self, name: &str, ids: &[u32]) -> Result<Tensor> {
                let view = self.get(name)?;
                match DType::try_from(view.dtype()) {
                    Ok(DType::BF16) => bf16_to_f32(view.shape(), view.data(), Some(ids)),
                    _ => {
                        let ids = Tensor::new(ids, &Device::Cpu)?;
                        self.load(name, &Device::Cpu)?
                            .index_select(&ids, 0)?
                            .to_dtype(DType::F32)
                    }
                }
            }
        }
    };
}

direct_bf16!(MmapedSafetensors);
direct_bf16!(SliceSafetensors<'_>);

#[cfg(test)]
mod tests {
    use super::*;

    /// Uses only `load`, so `load_f32` and `load_f32_rows` take the default (Candle) path.
    struct Plain<'a>(SliceSafetensors<'a>);

    impl WeightSource for Plain<'_> {
        fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
            self.0.load(name, device)
        }
    }

    fn safetensors(tensors: &[(&str, &str, &[usize], Vec<u8>)]) -> Vec<u8> {
        let mut header = serde_json::Map::new();
        let mut data = Vec::new();
        for (name, dtype, shape, bytes) in tensors {
            header.insert(
                (*name).into(),
                serde_json::json!({"dtype": dtype, "shape": shape,
                    "data_offsets": [data.len(), data.len() + bytes.len()]}),
            );
            data.extend_from_slice(bytes);
        }
        let header = serde_json::to_vec(&header).unwrap();
        let mut file = (header.len() as u64).to_le_bytes().to_vec();
        file.extend(header);
        file.extend(data);
        file
    }

    fn bits(t: &Tensor) -> Vec<u32> {
        t.flatten_all()
            .unwrap()
            .to_vec1::<f32>()
            .unwrap()
            .iter()
            .map(|v| v.to_bits())
            .collect()
    }

    #[test]
    fn direct_conversion_is_bitwise_equal_to_candle() -> Result<()> {
        // Normal values, zeros, infinities, subnormals, a quiet and a signalling NaN, extremes.
        let special = [
            0x3f80_u16, 0xbf80, 0x0000, 0x8000, 0x7f80, 0xff80, 0x0001, 0x807f, 0x7fc0, 0x7f81,
            0xff81, 0x7f7f, 0xff7f, 0x0080, 0x4049, 0xc2f7,
        ];
        let words: Vec<u16> = (0..64_u16)
            .map(|i| special[usize::from(i) % special.len()] ^ (i / 16))
            .collect();
        let bf16_bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        let f32_bytes: Vec<u8> = (0..6)
            .flat_map(|i| (i as f32 - 2.5).to_le_bytes())
            .collect();
        let file = safetensors(&[
            ("matrix", "BF16", &[16, 4], bf16_bytes.clone()),
            ("vector", "BF16", &[64], bf16_bytes),
            ("float", "F32", &[3, 2], f32_bytes),
        ]);
        let direct = SliceSafetensors::new(&file)?;
        let plain = Plain(SliceSafetensors::new(&file)?);
        for name in ["matrix", "vector", "float"] {
            assert_eq!(
                bits(&direct.load_f32(name)?),
                bits(&plain.load_f32(name)?),
                "{name}"
            );
        }
        for ids in [&[0_u32][..], &[15, 0, 3, 3, 7], &[]] {
            assert_eq!(
                bits(&direct.load_f32_rows("matrix", ids)?),
                bits(&plain.load_f32_rows("matrix", ids)?),
                "{ids:?}"
            );
            let direct = direct.load_f32_rows("matrix", ids)?;
            assert_eq!(direct.dims(), [ids.len(), 4]);
        }
        assert_eq!(
            bits(&direct.load_f32_rows("float", &[2, 0])?),
            bits(&plain.load_f32_rows("float", &[2, 0])?)
        );
        assert!(direct.load_f32_rows("matrix", &[16]).is_err());
        assert!(direct.load_f32_rows("vector", &[0]).is_err());
        Ok(())
    }
}
