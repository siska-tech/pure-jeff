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

    /// The shape of the named tensor when [`load_f32_into`](Self::load_f32_into) converts it
    /// into a caller's buffer; `None` otherwise. Sources that hand out tensors they keep (for
    /// example retained F32 weights) return `None`, so their tensors are never overwritten.
    fn convertible_shape(&self, _name: &str) -> Option<Vec<usize>> {
        None
    }

    /// Writes the named tensor, converted to F32, into `out` (row-major) and returns `true`;
    /// `false` when this source does not convert into a buffer. Fails unless the tensor has
    /// exactly `shape`. Must give bitwise the same values as [`load_f32`](Self::load_f32).
    fn load_f32_into(&self, _name: &str, _shape: &[usize], _out: &mut [f32]) -> Result<bool> {
        Ok(false)
    }
}

/// Little-endian BF16 bytes converted into `out`, with the same `bf16::to_f32` as Candle.
fn bf16_into(data: &[u8], out: &mut [f32]) -> Result<()> {
    if data.len() != 2 * out.len() {
        candle_core::bail!(
            "BF16 tensor of {} bytes into {} values",
            data.len(),
            out.len()
        )
    }
    for (o, b) in out.iter_mut().zip(data.as_chunks::<2>().0) {
        *o = bf16::from_le_bytes(*b).to_f32();
    }
    Ok(())
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

            fn convertible_shape(&self, name: &str) -> Option<Vec<usize>> {
                let view = self.get(name).ok()?;
                DType::try_from(view.dtype())
                    .is_ok_and(|d| d == DType::BF16)
                    .then(|| view.shape().to_vec())
            }

            fn load_f32_into(&self, name: &str, shape: &[usize], out: &mut [f32]) -> Result<bool> {
                let view = self.get(name)?;
                if !DType::try_from(view.dtype()).is_ok_and(|d| d == DType::BF16) {
                    return Ok(false);
                }
                if view.shape() != shape {
                    candle_core::bail!("{name} has shape {:?}, not {shape:?}", view.shape())
                }
                bf16_into(view.data(), out)?;
                Ok(true)
            }
        }
    };
}

direct_bf16!(MmapedSafetensors);
direct_bf16!(SliceSafetensors<'_>);

/// A source whose named tensors were converted to F32 once and are kept; every other request
/// (embedding rows, raw tensors, tensors not listed) goes to `inner`. The kept values are the
/// ones `inner.load_f32` gave, so decisions are bitwise unchanged.
pub struct Retained<S> {
    inner: S,
    tensors: std::collections::HashMap<String, Tensor>,
}

impl<S: WeightSource> Retained<S> {
    /// Keeps nothing: every request goes to `inner`.
    pub fn none(inner: S) -> Self {
        Self {
            inner,
            tensors: Default::default(),
        }
    }

    /// Converts and keeps `names`; `check` runs between tensors (e.g. a deadline).
    pub fn new<'n>(
        inner: S,
        names: impl IntoIterator<Item = &'n str>,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        let mut tensors = std::collections::HashMap::new();
        for name in names {
            check()?;
            tensors.insert(name.to_owned(), inner.load_f32(name)?);
        }
        Ok(Self { inner, tensors })
    }

    /// Bytes of the kept F32 values.
    pub fn retained_bytes(&self) -> usize {
        self.tensors.values().map(|t| t.elem_count() * 4).sum()
    }
}

impl<S: WeightSource> WeightSource for Retained<S> {
    fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
        self.inner.load(name, device)
    }

    fn load_f32(&self, name: &str) -> Result<Tensor> {
        match self.tensors.get(name) {
            Some(t) => Ok(t.clone()),
            None => self.inner.load_f32(name),
        }
    }

    fn load_f32_rows(&self, name: &str, ids: &[u32]) -> Result<Tensor> {
        self.inner.load_f32_rows(name, ids)
    }

    fn convertible_shape(&self, name: &str) -> Option<Vec<usize>> {
        if self.tensors.contains_key(name) {
            return None;
        }
        self.inner.convertible_shape(name)
    }

    fn load_f32_into(&self, name: &str, shape: &[usize], out: &mut [f32]) -> Result<bool> {
        if self.tensors.contains_key(name) {
            return Ok(false);
        }
        self.inner.load_f32_into(name, shape, out)
    }
}

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
