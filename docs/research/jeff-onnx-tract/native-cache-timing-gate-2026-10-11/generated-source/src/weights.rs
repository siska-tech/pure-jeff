//! Experimental CPU weight ownership, separate from the Native reference.
use candle_core::{safetensors::MmapedSafetensors, DType, Device, Result, Tensor};
use std::collections::BTreeMap;
#[path = "text_inventory.rs"]
mod text_inventory;

fn text_weight_names(mut names: Vec<String>) -> Result<Vec<String>> {
    names.sort();
    if names == ["weight"] {
        return Ok(names); // Separate, verified Decision Head file.
    }
    if !names
        .iter()
        .map(String::as_str)
        .eq(text_inventory::ALL_NAMES.iter().copied())
    {
        candle_core::bail!("checkpoint tensor inventory differs from pinned full model")
    }
    Ok(text_inventory::TEXT_NAMES
        .iter()
        .map(|name| (*name).to_owned())
        .collect())
}

pub enum Weights {
    Mapped(MmapedSafetensors),
    Retained(BTreeMap<String, Tensor>),
}

impl Weights {
    pub fn from_mapped(
        mapped: MmapedSafetensors,
        retain: bool,
        check: &dyn Fn() -> Result<()>,
    ) -> Result<Self> {
        if !retain {
            return Ok(Self::Mapped(mapped));
        }
        let names =
            text_weight_names(mapped.tensors().into_iter().map(|(name, _)| name).collect())?;
        let mut tensors = BTreeMap::new();
        for name in names {
            check()?;
            let tensor = mapped.load(&name, &Device::Cpu)?.to_dtype(DType::F32)?;
            if tensors.insert(name, tensor).is_some() {
                candle_core::bail!("duplicate retained weight")
            }
        }
        check()?;
        // Tensor data are owned. The original mmap is released at this return.
        Ok(Self::Retained(tensors))
    }

    pub fn load(&self, name: &str, device: &Device) -> Result<Tensor> {
        match self {
            Self::Mapped(mapped) => mapped.load(name, device),
            Self::Retained(tensors) => {
                if !device.is_cpu() {
                    candle_core::bail!("retained experiment is CPU only")
                }
                tensors.get(name).cloned().ok_or_else(|| {
                    candle_core::Error::Msg(format!("missing retained weight: {name}"))
                })
            }
        }
    }

    pub fn retained_size(&self) -> (usize, usize) {
        match self {
            Self::Mapped(_) => (0, 0),
            Self::Retained(tensors) => (
                tensors.len(),
                tensors.values().map(|t| t.elem_count() * 4).sum(),
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_lookup_shares_tensor_and_rejects_missing() -> Result<()> {
        let tensor = Tensor::new(&[1_f32, -2.0, 0.0], &Device::Cpu)?;
        let id = tensor.id();
        let weights = Weights::Retained(BTreeMap::from([("weight".into(), tensor)]));
        assert_eq!(weights.load("weight", &Device::Cpu)?.id(), id);
        assert_eq!(weights.load("weight", &Device::Cpu)?.dtype(), DType::F32);
        assert!(weights.load("absent", &Device::Cpu).is_err());
        assert_eq!(weights.retained_size(), (1, 12));
        Ok(())
    }

    #[test]
    fn bf16_embedding_select_commutes_with_fp32_retention() -> Result<()> {
        let tensor =
            Tensor::new(&[[1.1_f32, -2.2], [0.0, 3.3]], &Device::Cpu)?.to_dtype(DType::BF16)?;
        let ids = Tensor::new(&[1_u32, 0, 1], &Device::Cpu)?;
        let before = tensor.index_select(&ids, 0)?.to_dtype(DType::F32)?;
        let after = tensor.to_dtype(DType::F32)?.index_select(&ids, 0)?;
        assert_eq!(before.to_vec2::<f32>()?, after.to_vec2::<f32>()?);
        Ok(())
    }
}

#[cfg(test)]
mod selection_tests {
    use super::*;
    fn complete() -> Vec<String> {
        text_inventory::ALL_NAMES
            .iter()
            .rev()
            .map(|s| (*s).to_owned())
            .collect()
    }
    #[test]
    fn selects_exact_text_inventory_from_unordered_full_model() -> Result<()> {
        let selected = text_weight_names(complete())?;
        assert_eq!(selected.len(), 320);
        assert!(selected.iter().all(|s| s.starts_with("language_model.")));
        assert!(selected
            .iter()
            .map(String::as_str)
            .eq(text_inventory::TEXT_NAMES.iter().copied()));
        Ok(())
    }
    #[test]
    fn rejects_missing_duplicate_and_unexpected_model_names() {
        let mut missing = complete();
        missing.pop();
        assert!(text_weight_names(missing).is_err());
        let mut duplicate = complete();
        duplicate.push(duplicate[0].clone());
        assert!(text_weight_names(duplicate).is_err());
        let mut unexpected = complete();
        unexpected[0] = "unexpected.weight".into();
        assert!(text_weight_names(unexpected).is_err());
    }
    #[test]
    fn preserves_head_and_rejects_ambiguous_file() -> Result<()> {
        assert_eq!(text_weight_names(vec!["weight".into()])?, vec!["weight"]);
        assert!(text_weight_names(vec!["weight".into(), "extra".into()]).is_err());
        assert!(text_weight_names(vec![]).is_err());
        Ok(())
    }
}
