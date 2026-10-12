use candle_core::{
    safetensors::{MmapedSafetensors, SliceSafetensors},
    Device, Result, Tensor,
};

/// Named tensors of a checkpoint: memory-mapped files (Native) or bytes held in memory
/// (browser). The backbone and readout read their weights only through this trait.
pub trait WeightSource {
    fn load(&self, name: &str, device: &Device) -> Result<Tensor>;
}

impl WeightSource for MmapedSafetensors {
    fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
        MmapedSafetensors::load(self, name, device)
    }
}

impl WeightSource for SliceSafetensors<'_> {
    fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
        SliceSafetensors::load(self, name, device)
    }
}
