"""Generate a timing wrapper with explicit cache init and original request output."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
from benchmark_pilot import ROOT, save, sha
from prepare_native_retained import replace_once


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    base=ROOT/'.venv/native-threads-candidate'
    prior=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
    pre=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    diagnostic=prior/'generated-source'
    for a in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):
        if sha(prior/a['path'])!=a['sha256']:raise ValueError('previous archive changed')
    generation=json.loads((base/'generation.json').read_text(encoding='utf-8'))
    if sha(base/'generation.json')!=json.loads((diagnostic/'generation.json').read_text(encoding='utf-8'))['previous_generation_sha256']:
        raise ValueError('frozen thread wrapper changed')
    args.output.mkdir(parents=True,exist_ok=False)
    for a in generation['files']:
        if sha(base/a['path'])!=a['sha256']:raise ValueError('frozen source changed')
        dest=args.output/a['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(base/a['path'],dest)
    # Same dependency graph/features and cache module as the accepted diagnostic.
    manifest=(diagnostic/'Cargo.toml').read_text(encoding='utf-8')
    (args.output/'Cargo.toml').write_text(replace_once(manifest,'name = "native_cache_diagnostic"','name = "native_cache_fixed_bench"'),encoding='utf-8')
    shutil.copyfile(diagnostic/'Cargo.lock',args.output/'Cargo.lock')
    shutil.copyfile(diagnostic/'src/cache_diagnostic.rs',args.output/'src/cache_diagnostic.rs')
    path=args.output/'src/main.rs';original=path.read_text(encoding='utf-8')
    text=replace_once(original,'mod backbone;','mod backbone;\nmod cache_diagnostic;')
    text=replace_once(text,'    let deadline = started + Duration::from_secs(600);','''    if args[0] == "--cache-probe" {
        emit(cache_diagnostic::initialize(args[1].parse()?)?)?;
        return Ok(());
    }
    let deadline = started + Duration::from_secs(600);''')
    text=replace_once(text,'    let requested_threads = threads::configure(&job)?;','''    let cache_diagnostic = cache_diagnostic::initialize(job["cache_init_cpu"].as_u64().ok_or_else(|| anyhow::anyhow!("cache_init_cpu required"))? as usize)?;
    let requested_threads = threads::configure(&job)?;''')
    text=replace_once(text,'"event":"initialized","backend":"native",','"event":"initialized","backend":"native","cache_diagnostic":cache_diagnostic,')
    path.write_text(text,encoding='utf-8')
    subprocess.run(['rustfmt','--edition','2021',str(path)],check=True)
    (args.output/'main.rs.cache-fixed.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),path.read_text(encoding='utf-8').splitlines(True),fromfile='frozen-main.rs',tofile='cache-fixed-main.rs',n=0)),encoding='utf-8')
    for name in ['backbone.rs','weights.rs','readout.rs','threads.rs']:
        if sha(base/'src'/name)!=sha(args.output/'src'/name):raise ValueError('compute source changed')
    save(args.output/'generation.json',{'generator_sha256':sha(__file__),'previous_generation_sha256':sha(base/'generation.json'),
        'diagnostic_generation_sha256':pre['generation_sha256'],
        'files':[{'path':p.relative_to(args.output).as_posix(),'sha256':sha(p)} for p in sorted(args.output.rglob('*')) if p.is_file()],
        'scope':'explicit cache init before pool/model/forward, restore main thread mask; original request output and backbone/weights/readout/threads unchanged',
        'runtime_api_changed':False,'performance_acceptance':False})
    print('cache-fixed timing wrapper generated')


if __name__=='__main__':main()
