//! Diagnostic: the CPU this process started on and the cache sizes gemm uses for its kernel
//! parameters (`gemm_common::cache::CACHE_INFO`, read once per process from the CPU it is
//! first called on). Run it pinned to each logical CPU to see whether the values differ.
use serde_json::json;

#[cfg(windows)]
fn current_cpu() -> u32 {
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcessorNumber() -> u32;
    }
    // SAFETY: no arguments; returns the number of the processor running this thread.
    unsafe { GetCurrentProcessorNumber() }
}

#[cfg(not(windows))]
fn current_cpu() -> u32 {
    u32::MAX
}

fn main() {
    let before = current_cpu();
    let caches: Vec<_> = gemm_common::cache::CACHE_INFO
        .iter()
        .map(|c| {
            json!({"bytes": c.cache_bytes, "associativity": c.associativity,
                   "line_bytes": c.cache_line_bytes})
        })
        .collect();
    println!(
        "{}",
        json!({"cpu_at_start": before, "cpu_after": current_cpu(),
               "candle_threads": candle_core::utils::get_num_threads(), "gemm_cache_info": caches})
    );
}
