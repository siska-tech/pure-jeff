use anyhow::{ensure, Result};
use serde_json::{json, Value};
use std::ffi::c_void;

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentThread() -> *mut c_void;
    fn GetCurrentProcess() -> *mut c_void;
    fn GetCurrentProcessorNumber() -> u32;
    fn GetProcessAffinityMask(
        process: *mut c_void,
        process_mask: *mut usize,
        system_mask: *mut usize,
    ) -> i32;
    fn SetThreadAffinityMask(thread: *mut c_void, mask: usize) -> usize;
}

pub fn processor() -> u32 {
    unsafe { GetCurrentProcessorNumber() }
}

pub fn initialize(cpu: usize) -> Result<Value> {
    ensure!(
        cpu < usize::BITS as usize,
        "CPU index exceeds single-group mask"
    );
    let mut allowed = 0usize;
    let mut system = 0usize;
    ensure!(
        unsafe { GetProcessAffinityMask(GetCurrentProcess(), &mut allowed, &mut system) } != 0,
        "process affinity unavailable"
    );
    ensure!(
        allowed & (1usize << cpu) != 0,
        "CPU not in process affinity mask"
    );
    let previous = unsafe { SetThreadAffinityMask(GetCurrentThread(), 1usize << cpu) };
    ensure!(previous != 0, "pinning failed");
    // Restore even if a cache read panics. Only this diagnostic main thread is pinned.
    struct Restore(usize);
    impl Drop for Restore {
        fn drop(&mut self) {
            unsafe {
                SetThreadAffinityMask(GetCurrentThread(), self.0);
            }
        }
    }
    let restore = Restore(previous);
    let actual = processor();
    ensure!(actual as usize == cpu, "pinning processor mismatch");
    let info = *gemm_common::cache::CACHE_INFO;
    let entries: Vec<Value> = info
        .iter()
        .map(|v| {
            json!({"cache_bytes":v.cache_bytes,
        "associativity":v.associativity,"cache_line_bytes":v.cache_line_bytes})
        })
        .collect();
    // Hypothetical parameter samples; these are NOT telemetry of actual GEMM calls.
    let samples: Vec<Value> = [128,512].into_iter().map(|m| {
        let v = gemm_common::cache::kernel_params(m,1024,1024,8,8,4);
        json!({"m":m,"n":1024,"k":1024,"mr":8,"nr":8,"scalar_bytes":4,"kc":v.kc,"mc":v.mc,"nc":v.nc})
    }).collect();
    let restored = unsafe { SetThreadAffinityMask(GetCurrentThread(), previous) };
    ensure!(restored != 0, "affinity restoration failed");
    std::mem::forget(restore);
    Ok(
        json!({"requested_cpu":cpu,"actual_cpu_at_initialization":actual,
        "process_allowed_mask":allowed,"system_mask":system,"thread_mask_restored":previous,
        "cache_info":entries,"hypothetical_kernel_params":samples,"affinity_restored":true}),
    )
}
