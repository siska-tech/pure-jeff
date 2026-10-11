"""Generate isolated Native text320 thread-matrix wrapper; preserve frozen binaries."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
from benchmark_pilot import ROOT,save,sha
from prepare_native_retained import replace_once

THREADS='''use anyhow::{ensure, Result};
use serde_json::Value;

pub fn requested(job: &Value) -> Result<usize> {
    let n = job["threads"].as_u64().ok_or_else(|| anyhow::anyhow!("threads must be an integer"))?;
    ensure!([1, 2, 4, 8].contains(&n), "unsupported compute thread count");
    Ok(n as usize)
}

pub fn configure(job: &Value) -> Result<usize> {
    let n = requested(job)?;
    // Standalone process, before any tokenizer/tensor/pool initialization.
    std::env::set_var("RAYON_NUM_THREADS", n.to_string());
    std::env::set_var("CANDLE_NUM_THREADS", n.to_string());
    rayon::ThreadPoolBuilder::new().num_threads(n).build_global()?;
    ensure!(rayon::current_num_threads() == n, "Rayon pool size mismatch");
    ensure!(candle_core::utils::get_num_threads() == n, "Candle GEMM setting mismatch");
    Ok(n)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_supported_integer_counts() -> Result<()> {
        for n in [1, 2, 4, 8] { assert_eq!(requested(&serde_json::json!({"threads": n}))?, n); }
        Ok(())
    }
    #[test]
    fn rejects_missing_invalid_and_unsupported_counts() {
        for value in [serde_json::json!({}), serde_json::json!({"threads": null}),
            serde_json::json!({"threads": "4"}), serde_json::json!({"threads": 4.0}),
            serde_json::json!({"threads": -1}), serde_json::json!({"threads": 0}),
            serde_json::json!({"threads": 3}), serde_json::json!({"threads": 16}),
            serde_json::json!({"threads": true}), serde_json::json!({"threads": u64::MAX})] {
            assert!(requested(&value).is_err());
        }
    }
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    prior=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11'
    for item in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):
        if sha(prior/item['path'])!=item['sha256']:raise ValueError('text evidence changed')
    old=json.loads((prior/'generation.json').read_text(encoding='utf-8'))
    for p,h in old['sources'].items():
        if sha(ROOT/p)!=h:raise ValueError('Native source changed')
    args.output.mkdir(parents=True,exist_ok=False)
    for item in old['files']:
        p=args.output/item['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(prior/'generated'/item['path'],p)
    main_rs=args.output/'src/main.rs';original=main_rs.read_text(encoding='utf-8')
    new=replace_once(original,'mod weights;','mod weights;\nmod threads;')
    new=replace_once(new,'    std::env::set_var("CANDLE_NUM_THREADS", "1");\n    std::env::set_var("RAYON_NUM_THREADS", "1");','    let requested_threads = threads::configure(&job)?;')
    new=replace_once(new,'"threads":candle_core::utils::get_num_threads(),','"threads":candle_core::utils::get_num_threads(),"requested_threads":requested_threads,"rayon_pool_threads":rayon::current_num_threads(),"candle_env_threads":std::env::var("CANDLE_NUM_THREADS")?,"expected_barrier_aux_workers":requested_threads-1,"manifest_cpu_threads":header.policy.cpu_threads,')
    main_rs.write_text(new,encoding='utf-8');(args.output/'src/threads.rs').write_text(THREADS,encoding='utf-8')
    manifest=args.output/'Cargo.toml';s=manifest.read_text(encoding='utf-8');manifest.write_text(replace_once(s,'anyhow = "1"','anyhow = "1"\nrayon = "=1.12.0"'),encoding='utf-8')
    lock=args.output/'Cargo.lock';s=lock.read_text(encoding='utf-8')
    root=s.index('name = "kaze_judge_native_bench"');end=s.index('\n[[package]]',root)
    s=s[:root]+replace_once(s[root:end],' "serde_json",',' "rayon",\n "serde_json",')+s[end:];lock.write_text(s,encoding='utf-8')
    a=tomllib.loads((prior/'generated/Cargo.lock').read_text(encoding='utf-8'));b=tomllib.loads(s)
    if [x for x in a['package'] if x['name']!='kaze_judge_native_bench']!=[x for x in b['package'] if x['name']!='kaze_judge_native_bench']:raise ValueError('dependency packages changed')
    subprocess.run(['rustfmt','--edition','2021',str(main_rs),str(args.output/'src/threads.rs')],check=True)
    (args.output/'thread-wrapper.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),main_rs.read_text(encoding='utf-8').splitlines(True),fromfile='text320-main',tofile='thread-matrix-main',n=0)),encoding='utf-8')
    save(args.output/'generation.json',{'generator_sha256':sha(__file__),'anchor_helper_sha256':sha(ROOT/'runtime/onnx/prepare_native_retained.py'),
        'previous_generation_sha256':sha(prior/'generation.json'),'sources':old['sources'],
        'files':[{'path':p.relative_to(args.output).as_posix(),'sha256':sha(p)} for p in sorted(args.output.rglob('*')) if p.is_file()],
        'scope':'only experimental thread wrapper; text320 weights/equations unchanged, Rayon existing locked dependency made explicit',
        'threads':[1,2,4,8],'policy_cpu_threads':1,'runtime_api_changed':False})
    print('generated isolated thread wrapper, dependency versions preserved',flush=True)

if __name__=='__main__':main()
