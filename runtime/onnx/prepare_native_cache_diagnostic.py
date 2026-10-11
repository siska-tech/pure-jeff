"""Generate an isolated cache-initialization/hidden-output diagnostic wrapper."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
from benchmark_pilot import ROOT, save, sha
from prepare_native_retained import replace_once

CACHE_RS = r'''use anyhow::{ensure, Result};
use serde_json::{json, Value};
use std::ffi::c_void;

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentThread() -> *mut c_void;
    fn GetCurrentProcess() -> *mut c_void;
    fn GetCurrentProcessorNumber() -> u32;
    fn GetProcessAffinityMask(process: *mut c_void, process_mask: *mut usize, system_mask: *mut usize) -> i32;
    fn SetThreadAffinityMask(thread: *mut c_void, mask: usize) -> usize;
}

pub fn processor() -> u32 { unsafe { GetCurrentProcessorNumber() } }

pub fn initialize(cpu: usize) -> Result<Value> {
    ensure!(cpu < usize::BITS as usize, "CPU index exceeds single-group mask");
    let mut allowed = 0usize;
    let mut system = 0usize;
    ensure!(unsafe { GetProcessAffinityMask(GetCurrentProcess(), &mut allowed, &mut system) } != 0, "process affinity unavailable");
    ensure!(allowed & (1usize << cpu) != 0, "CPU not in process affinity mask");
    let previous = unsafe { SetThreadAffinityMask(GetCurrentThread(), 1usize << cpu) };
    ensure!(previous != 0, "pinning failed");
    // Restore even if a cache read panics. Only this diagnostic main thread is pinned.
    struct Restore(usize);
    impl Drop for Restore { fn drop(&mut self) { unsafe { SetThreadAffinityMask(GetCurrentThread(), self.0); } } }
    let restore = Restore(previous);
    let actual = processor();
    ensure!(actual as usize == cpu, "pinning processor mismatch");
    let info = *gemm_common::cache::CACHE_INFO;
    let entries: Vec<Value> = info.iter().map(|v| json!({"cache_bytes":v.cache_bytes,
        "associativity":v.associativity,"cache_line_bytes":v.cache_line_bytes})).collect();
    // Hypothetical parameter samples; these are NOT telemetry of actual GEMM calls.
    let samples: Vec<Value> = [128,512].into_iter().map(|m| {
        let v = gemm_common::cache::kernel_params(m,1024,1024,8,8,4);
        json!({"m":m,"n":1024,"k":1024,"mr":8,"nr":8,"scalar_bytes":4,"kc":v.kc,"mc":v.mc,"nc":v.nc})
    }).collect();
    let restored = unsafe { SetThreadAffinityMask(GetCurrentThread(), previous) };
    ensure!(restored != 0, "affinity restoration failed");
    std::mem::forget(restore);
    Ok(json!({"requested_cpu":cpu,"actual_cpu_at_initialization":actual,
        "process_allowed_mask":allowed,"system_mask":system,"thread_mask_restored":previous,
        "cache_info":entries,"hypothetical_kernel_params":samples,"affinity_restored":true}))
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    source = ROOT/'.venv/native-threads-candidate'
    old = json.loads((source/'generation.json').read_text(encoding='utf-8'))
    frozen = json.loads((ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11/preregistration.json').read_text(encoding='utf-8'))
    if sha(source/'generation.json') != frozen['generation_sha256']:
        raise ValueError('thread wrapper generation changed')
    args.output.mkdir(parents=True, exist_ok=False)
    for item in old['files']:
        if sha(source/item['path']) != item['sha256']:
            raise ValueError('frozen generated source changed')
        target = args.output/item['path']; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source/item['path'], target)
    p = args.output/'Cargo.toml'; original = p.read_text(encoding='utf-8')
    modified = replace_once(original, 'anyhow = "1"', 'anyhow = "1"\ngemm-common = { version = "=0.19.0", default-features = false }')
    modified = replace_once(modified, 'name = "native_retained_bench"', 'name = "native_cache_diagnostic"')
    p.write_text(modified, encoding='utf-8')
    p = args.output/'Cargo.lock'; original = p.read_text(encoding='utf-8')
    start = original.index('name = "kaze_judge_native_bench"'); end = original.index('\n[[package]]', start)
    modified = original[:start]+replace_once(original[start:end], ' "candle-nn",', ' "candle-nn",\n "gemm-common",')+original[end:]
    p.write_text(modified, encoding='utf-8')
    a = tomllib.loads(original); b = tomllib.loads(modified)
    if [v for v in a['package'] if v['name'] != 'kaze_judge_native_bench'] != [v for v in b['package'] if v['name'] != 'kaze_judge_native_bench']:
        raise ValueError('dependency package/version changed')
    p = args.output/'src/main.rs'; original = p.read_text(encoding='utf-8')
    text = replace_once(original, 'mod backbone;', 'mod backbone;\nmod cache_diagnostic;')
    text = replace_once(text, '    let deadline = started + Duration::from_secs(600);', '''    if args[0] == "--cache-probe" {
        emit(cache_diagnostic::initialize(args[1].parse()?)?)?;
        return Ok(());
    }
    let deadline = started + Duration::from_secs(600);''')
    text = replace_once(text, '    let requested_threads = threads::configure(&job)?;', '''    let cache_diagnostic = cache_diagnostic::initialize(job["cache_init_cpu"].as_u64().ok_or_else(|| anyhow::anyhow!("cache_init_cpu required"))? as usize)?;
    let requested_threads = threads::configure(&job)?;''')
    text = replace_once(text, '"event":"initialized","backend":"native",', '"event":"initialized","backend":"native","cache_diagnostic":cache_diagnostic,')
    text = replace_once(text, '        let hidden = backbone::forward_checked', '        let processor_before = cache_diagnostic::processor();\n        let hidden = backbone::forward_checked')
    text = replace_once(text, '        let probabilities = if let Some(head)', '        let (probabilities, raw_logits) = if let Some(head)')
    old_else = '''            kaze_judge_jeff::readout::probabilities(
                &bundle.root,
                &hidden,
                request.candidates.len(),
                bundle.decision.temperature,
            )?'''
    text = replace_once(text, old_else, '            anyhow::bail!("diagnostic requires retained head")')
    text = replace_once(text, '        emit(\n            json!({"event":"request",', '''        let processor_after = cache_diagnostic::processor();
        let hidden_values = hidden.flatten_all()?.to_vec1::<f32>()?;
        emit(
            json!({"input_ids":prepared.ids,"hidden_values":hidden_values,"raw_logits":raw_logits,
            "processor_before":processor_before,"processor_after":processor_after,"event":"request",''')
    p.write_text(text, encoding='utf-8')
    p = args.output/'src/readout.rs'; readout_old = p.read_text(encoding='utf-8')
    text = replace_once(readout_old, ') -> Result<Vec<f64>> {', ') -> Result<(Vec<f64>, Vec<f32>)> {')
    text = replace_once(text, '    Ok(p.into_iter().map(f64::from).collect())', '    Ok((p.into_iter().map(f64::from).collect(), logits))')
    p.write_text(text, encoding='utf-8'); (args.output/'src/cache_diagnostic.rs').write_text(CACHE_RS, encoding='utf-8')
    subprocess.run(['rustfmt', '--edition', '2021', *[str(args.output/'src'/n) for n in ['main.rs','readout.rs','cache_diagnostic.rs']]], check=True)
    for name, before in [('main.rs', original), ('readout.rs', readout_old)]:
        (args.output/(name+'.diagnostic.patch')).write_text(''.join(difflib.unified_diff(before.splitlines(True), (args.output/'src'/name).read_text(encoding='utf-8').splitlines(True), fromfile='frozen-'+name, tofile='diagnostic-'+name, n=0)), encoding='utf-8')
    save(args.output/'generation.json', {'generator_sha256':sha(__file__), 'previous_generation_sha256':sha(source/'generation.json'),
        'files':[{'path':p.relative_to(args.output).as_posix(),'sha256':sha(p)} for p in sorted(args.output.rglob('*')) if p.is_file()],
        'scope':'diagnostic main-thread affinity only during explicit cache initialization, restored before pool/model/forward; backbone equations unchanged; readout returns existing raw logits',
        'dependency_packages_versions_unchanged':True,'runtime_api_changed':False,'performance_acceptance':False})
    print('cache diagnostic generated')


if __name__ == '__main__':
    main()
