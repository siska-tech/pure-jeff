use anyhow::{ensure, Result};
use serde_json::Value;

pub fn requested(job: &Value) -> Result<usize> {
    let n = job["threads"]
        .as_u64()
        .ok_or_else(|| anyhow::anyhow!("threads must be an integer"))?;
    ensure!(
        [1, 2, 4, 8].contains(&n),
        "unsupported compute thread count"
    );
    Ok(n as usize)
}

pub fn configure(job: &Value) -> Result<usize> {
    let n = requested(job)?;
    // Standalone process, before any tokenizer/tensor/pool initialization.
    std::env::set_var("RAYON_NUM_THREADS", n.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", n.to_string());
    rayon::ThreadPoolBuilder::new()
        .num_threads(n)
        .build_global()?;
    ensure!(
        rayon::current_num_threads() == n,
        "Rayon pool size mismatch"
    );
    ensure!(
        candle_core::utils::get_num_threads() == n,
        "Candle GEMM setting mismatch"
    );
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_supported_integer_counts() -> Result<()> {
        for n in [1, 2, 4, 8] {
            assert_eq!(requested(&serde_json::json!({"threads": n}))?, n);
        }
        Ok(())
    }
    #[test]
    fn rejects_missing_invalid_and_unsupported_counts() {
        for value in [
            serde_json::json!({}),
            serde_json::json!({"threads": null}),
            serde_json::json!({"threads": "4"}),
            serde_json::json!({"threads": 4.0}),
            serde_json::json!({"threads": -1}),
            serde_json::json!({"threads": 0}),
            serde_json::json!({"threads": 3}),
            serde_json::json!({"threads": 16}),
            serde_json::json!({"threads": true}),
            serde_json::json!({"threads": u64::MAX}),
        ] {
            assert!(requested(&value).is_err());
        }
    }
}
