"""Record source-based compute-thread audit for the fixed Native FP32 pilot."""
import argparse
import json
from pathlib import Path
import subprocess

from benchmark_pilot import ROOT, save, sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    candle=Path('C:/Users/<user>/.cargo/git/checkouts/candle-5b4d092929d18d36/c68b249')
    commit=subprocess.check_output(['git','-C',str(candle),'rev-parse','HEAD'],text=True,encoding='utf-8').strip()
    if commit!='c68b24997319b8d76e5a4e775dab197c7f26322a':raise ValueError('Candle commit changed')
    subprocess.run(['git','-C',str(candle),'diff','--exit-code','--','candle-core','candle-nn'],check=True)
    features=subprocess.check_output(['cargo','tree','--locked','--offline','--manifest-path',str(ROOT/'.venv/native-text-candidate/Cargo.toml'),'-e','features'],text=True,encoding='utf-8')
    if any('candle-core feature "'+name+'"' in features for name in ['mkl','accelerate','cuda','metal']):raise ValueError('unexpected accelerated feature')
    paths={
        'utils':(candle/'candle-core/src/utils.rs',[(114,141),(360,425),(545,558)]),
        'matmul':(candle/'candle-core/src/cpu_backend/mod.rs',[(1442,1532)]),
        'elementwise':(candle/'candle-core/src/cpu_backend/utils.rs',[(365,440)]),
        'native_wrapper':(ROOT/'.venv/native-text-candidate/src/main.rs',[(30,44),(87,93)]),
        'native_backbone':(ROOT/'runtime/rust/src/backbone.rs',[(114,153)]),
        'tract_wrapper':(ROOT/'.venv/tract-scatter-candidate/src/bin/bench.rs',[(30,42)]),
    }
    sources={}
    for name,(path,ranges) in paths.items():
        lines=path.read_text(encoding='utf-8').splitlines()
        sources[name]={'path':str(path),'sha256':sha(path),'excerpts':[{'first_line':a,'last_line':b,'text':'\n'.join(lines[a-1:b])} for a,b in ranges]}
    wrapper=paths['native_wrapper'][0].read_text(encoding='utf-8')
    for anchor in ['ensure!(header.policy.cpu_threads == 1','set_var("CANDLE_NUM_THREADS", "1")','set_var("RAYON_NUM_THREADS", "1")']:
        if anchor not in wrapper:raise ValueError('fixed wrapper thread anchor changed')
    save(args.output,{'script_sha256':sha(__file__),'candle_commit':commit,'candle_core_nn_git_diff_exit_code':0,
        'cargo_features':features,'sources':sources,'compute_threads':1,
        'findings':['fixed Native wrapper sets both environment variables to 1 before tokenizer/tensor load',
            'get_num_threads reads RAYON_NUM_THREADS; GEMM selects Parallelism::None at 1',
            'large elementwise helpers use barrier_pool; CANDLE_NUM_THREADS=1 requests zero auxiliary workers',
            'Native DeltaNet time/head/state loops are serial Rust loops',
            'Tract uses explicit SingleThread executor at 1, validates executor size; multithread_mm feature remains compiled',
            'no MKL/Accelerate/CUDA/Metal Candle features enabled in fixed candidate dependency graph'],
        'limits':['source/configuration audit plus emitted compute setting; not OS active-thread telemetry',
            'tokenizer/runtime helper OS threads may exist; one compute thread is not one process thread',
            'Native wrapper rejects policy other than 1 and overwrites environment; external env cannot produce a 4-thread Native experiment',
            'new isolated Native wrapper and numerical gates required for future thread matrix',
            'FP32 retained dtype does not equalize packed layout, kernels, algorithm or timing boundaries']})
    print('PASS: fixed one-compute-thread paths audited; OS thread count not asserted')


if __name__=='__main__':
    main()
