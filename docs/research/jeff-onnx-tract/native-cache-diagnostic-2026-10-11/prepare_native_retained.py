"""Generate an isolated Native weight-retention experiment from frozen equations."""
import argparse
import difflib
import json
from pathlib import Path
import subprocess

from benchmark_pilot import ROOT, save, sha


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('source anchor changed: '+old[:60])
    return text.replace(old,new,1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
    if [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']] != ['.gitignore']:
        raise ValueError('Native baseline changed')
    args.output.mkdir(parents=True,exist_ok=False)
    src=args.output/'src';src.mkdir()
    sources={}
    def read(relative):
        path=ROOT/relative;sources[relative]=sha(path)
        return path.read_text(encoding='utf-8')
    backbone=read('runtime/rust/src/backbone.rs')
    adapted=replace_once(backbone,'use candle_core::{safetensors::MmapedSafetensors, DType, Device, Result, Tensor, D};',
        'use crate::weights::Weights;\nuse candle_core::{DType, Device, Result, Tensor, D};')
    adapted=adapted.replace('&MmapedSafetensors','&Weights')
    adapted=replace_once(adapted,'pub fn forward(weights:', '#[allow(dead_code)]\npub fn forward(weights:')
    if 'MmapedSafetensors' in adapted:raise ValueError('unadapted backbone weight type')
    (src/'backbone.rs').write_text(adapted,encoding='utf-8')
    readout=read('runtime/rust/src/readout.rs')
    head=replace_once(readout,'use candle_core::{safetensors::MmapedSafetensors, DType, Device, Tensor};\nuse std::path::Path;',
        'use candle_core::{DType, Device, Tensor};\nuse crate::weights::Weights;')
    head=replace_once(head,'root: &Path,','weights: &Weights,')
    head=replace_once(head,'    // SAFETY: caller verified the bundle and keeps its files immutable during inference.\n    let weights = unsafe { MmapedSafetensors::new(root.join("readout.safetensors"))? };\n','')
    (src/'readout.rs').write_text(head,encoding='utf-8')
    wrapper=read('runtime/bench-native/src/main.rs')
    wrapper=replace_once(wrapper,'    backbone,\n','')
    wrapper=replace_once(wrapper,'use anyhow::{ensure, Result};','mod backbone;\nmod readout;\nmod weights;\nuse anyhow::{ensure, Result};')
    wrapper=replace_once(wrapper,'    readout,\n','')
    wrapper=replace_once(wrapper,'    let mmap_ns = step.elapsed().as_nanos();',
        '''    let mmap_ns = step.elapsed().as_nanos();
    let retained = job["retained_f32"].as_bool().ok_or_else(|| anyhow::anyhow!("retained_f32 required"))?;
    let check_load = || {
        if Instant::now() >= deadline { candle_core::bail!("load deadline exceeded") } else { Ok(()) }
    };
    let step = Instant::now();
    let weights = weights::Weights::from_mapped(weights, retained, &check_load)?;
    let head_weights = if retained {
        // SAFETY: parent freezes the verified readout file for the experiment.
        let head = unsafe { candle_core::safetensors::MmapedSafetensors::new(bundle.root.join("readout.safetensors"))? };
        Some(weights::Weights::from_mapped(head, true, &check_load)?)
    } else { None };
    let retention_load_ns = step.elapsed().as_nanos();
    let (cached_tensors, cached_bytes) = weights.retained_size();
    let (head_cached_tensors, head_cached_bytes) = head_weights.as_ref().map_or((0,0), |w| w.retained_size());''')
    wrapper=replace_once(wrapper,'"retained":"tokenizer and BF16 mmap; FP32 conversion remains per forward"',
        '"retained_f32":retained,"retention_load_ns":retention_load_ns,"cached_tensors":cached_tensors,"cached_bytes":cached_bytes,"head_cached_tensors":head_cached_tensors,"head_cached_bytes":head_cached_bytes')
    start=wrapper.index('        let probabilities = readout::probabilities(')
    end=wrapper.index('        let head_softmax_ns',start)
    wrapper=wrapper[:start]+'''        let probabilities = if let Some(head) = &head_weights {
            readout::probabilities(head, &hidden, request.candidates.len(), bundle.decision.temperature)?
        } else {
            kaze_judge_jeff::readout::probabilities(&bundle.root, &hidden, request.candidates.len(), bundle.decision.temperature)?
        };
'''+wrapper[end:]
    (src/'main.rs').write_text(wrapper,encoding='utf-8')
    (src/'weights.rs').write_text(read('runtime/native-retained/weights.rs'),encoding='utf-8')
    cargo=read('runtime/bench-native/Cargo.toml')
    cargo=replace_once(cargo,'path = "../.."','path = '+json.dumps(ROOT.as_posix()))
    cargo=replace_once(cargo,'path = "../rust"','path = '+json.dumps((ROOT/'runtime/rust').as_posix()))
    candle_nn='candle-nn = { git = "https://github.com/huggingface/candle.git", rev = "c68b24997319b8d76e5a4e775dab197c7f26322a", default-features = false }\n'
    (args.output/'Cargo.toml').write_text(cargo+candle_nn+'\n[[bin]]\nname = "native_retained_bench"\npath = "src/main.rs"\n',encoding='utf-8')
    lock=read('runtime/bench-native/Cargo.lock')
    lock=replace_once(lock,'name = "kaze_judge_native_bench"\nversion = "0.1.0"\ndependencies = [\n "anyhow",\n "candle-core",',
        'name = "kaze_judge_native_bench"\nversion = "0.1.0"\ndependencies = [\n "anyhow",\n "candle-core",\n "candle-nn",')
    (args.output/'Cargo.lock').write_text(lock,encoding='utf-8')
    subprocess.run(['rustfmt','--edition','2021',*[str(p) for p in sorted(src.glob('*.rs'))]],check=True)
    for name,before,file in [('backbone',backbone,'backbone.rs'),('readout',readout,'readout.rs'),('wrapper',read('runtime/bench-native/src/main.rs'),'main.rs')]:
        after=(src/file).read_text(encoding='utf-8')
        (args.output/(name+'.patch')).write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='original',tofile='generated',n=0)),encoding='utf-8')
    save(args.output/'generation.json',{'sources':sources,'generator_sha256':sha(__file__),
        'rustfmt_version':subprocess.check_output(['rustfmt','--version'],text=True).strip(),
        'files':[{'path':p.relative_to(args.output).as_posix(),'sha256':sha(p)} for p in sorted(args.output.rglob('*')) if p.is_file()],
        'scope':'equations unchanged, mmap vs owned FP32; same binary control/candidate, one compute thread; generated only'})
    print('generated isolated Native retention experiment',flush=True)


if __name__=='__main__':
    main()
