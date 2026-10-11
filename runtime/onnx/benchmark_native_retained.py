"""Numerical-gated single-binary Native FP32 weight-retention pilot."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import random

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    previous=ROOT/'docs/research/jeff-onnx-tract/common512-pilot-2026-10-11'
    for item in json.loads((previous/'file-index.json').read_text(encoding='utf-8')):
        if sha(previous/item['path'])!=item['sha256']:raise ValueError('previous evidence changed')
    cases=json.loads((previous/'reference-cases.json').read_text(encoding='utf-8'))
    refs={e['case']:e['probabilities'] for e in [json.loads(line) for line in (previous/'gate-native.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    generation=ROOT/'.venv/native-retained-v2/generation.json'
    generated=json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path'])!=item['sha256']:raise ValueError('generated source changed')
    for path,digest in generated['sources'].items():
        if sha(ROOT/path)!=digest:raise ValueError('Native/generator input changed')
    if sha(ROOT/'runtime/onnx/prepare_native_retained.py')!=generated['generator_sha256']:raise ValueError('generator changed')
    exe=ROOT/'.venv/native-retained-target/release/native_retained_bench.exe'
    manifest=ROOT/'models/jeff-rust-bundle-p3.json'
    policy=json.loads(manifest.read_text(encoding='utf-8'))['policy']
    previous_pre=json.loads((previous/'preregistration.json').read_text(encoding='utf-8'))
    assets=[a for a in previous_pre['assets'] if a['path'].startswith('models/') or a['path'].endswith('kaze_judge_native_bench.exe')]
    for item in assets:
        if sha(ROOT/item['path'])!=item['sha256']:raise ValueError('Native assets changed')
    if len(cases)!=8 or policy['cpu_threads']!=1 or any(x['tokens']!=512 for x in cases[4:]):raise ValueError('cohort mismatch')
    orders=[[False,True],[True,False],[False,True]]
    schedules=[]
    for block in range(3):
        measured=list(range(4,8));random.Random(1113512+block).shuffle(measured)
        schedules.append([{'case':4+block,'warmup':True}]+[{'case':i,'warmup':False} for i in measured])
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys<4*1024**3:raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),
        'script_sha256':sha(__file__),'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'),
        'executable_sha256':sha(exe),'generation_sha256':sha(generation),'assets':assets,
        'reference_cases_sha256':sha(previous/'reference-cases.json'),'previous_native_raw_sha256':sha(previous/'gate-native.stdout.jsonl'),
        'orders':orders,'schedules':schedules,'seed':1113512,'threads':1,'physical_tokens':512,'effective_tokens':512,
        'sessions_per_mode':3,'warmups_per_session':1,'samples_per_session':4,'samples_per_mode':12,'gate_cases_per_mode':8,
        'timeout_seconds':600,'memory_limit_bytes':limit,'available_physical_bytes':memory.ullAvailPhys,
        'numerical_acceptance':'probability/judgment/tokens gates plus all probabilities exactly equal frozen Native gate',
        'performance_acceptance':'local warm-only acceptance iff all three paired session medians, pooled median and p95 improve; no SLO/backend adoption',
        'formal_slo_acceptance':False,'scope':'one binary, original equations, BF16 mmap/per-forward conversion vs owned FP32 all model/readout tensors; batch1 common512',
        'limitations':['synthetic four inputs, n=12 p95=max, three independent pairs, one warmup',
            'initialization/peak n=3 incidental, not cold campaign; memory includes mapped/shared pages',
            'thermals/affinity/background/storage cache uncontrolled; hashes preflighted before timing',
            'no Tract comparison, API E2E, recognition quality or product API change']})
    rows=[]
    def run(retained,run_id,schedule):
        job=args.output/(run_id+'.job.json')
        save(job,{'retained_f32':retained,'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True)
        row=invoke([exe.resolve(),manifest.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,policy,expected_threads=1)
        init=events[0]
        if len(events)!=len(schedule)+2 or init['retained_f32']!=retained:raise ValueError('mode/schedule mismatch')
        if retained:
            if init['cached_tensors']<=0 or init['cached_bytes']<=2*1024**3 or init['head_cached_tensors']!=1:raise ValueError('FP32 retention incomplete')
        elif any(init[key] for key in ['cached_tensors','cached_bytes','head_cached_tensors','head_cached_bytes']):raise ValueError('control cache unexpectedly enabled')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            if event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['physical_tokens']!=case['tokens']:raise ValueError('shape/schedule mismatch')
            if event['probabilities']!=refs[event['case']]:raise ValueError('Native probability bits changed')
            event['compute_ns']=event['backbone_ns']+event['head_softmax_ns']
        row.update(retained_f32=retained,events=events)
        save(args.output/(run_id+'.validated.json'),row);rows.append(row)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    gate=[{'case':i,'warmup':False} for i in range(8)]
    run(False,'gate-control',gate);run(True,'gate-retained',gate)
    for block,order in enumerate(orders):
        for retained in order:run(retained,f'resident-{block}-'+('retained' if retained else 'control'),schedules[block])
    summary={'processes':len(rows),'forwards':sum(len(r['events'])-2 for r in rows),'numeric_passed':True,
        'probabilities_exact_to_frozen_native':True,'formal_slo_acceptance':False,
        'max_probability_error':max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),'modes':{},'pairs':[]}
    for retained,name in [(False,'control'),(True,'retained')]:
        resident=[r for r in rows if r['retained_f32']==retained and r['run_id'].startswith('resident')]
        es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        summary['modes'][name]={'stages_seconds':{k:stats([e[k]/1e9 for e in es]) for k in ['compute_ns','backbone_ns','head_softmax_ns','tokenize_ns','policy_ns','request_ns']},
            'startup_seconds':stats([r['events'][0]['startup_ns']/1e9 for r in resident]),
            'retention_load_seconds':stats([r['events'][0]['retention_load_ns']/1e9 for r in resident]),
            'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs':{case['id']:stats([e['compute_ns']/1e9 for e in es if e['case']==case['id']]) for case in cases[4:]}}
    for block in range(3):
        pair={}
        for mode in ['control','retained']:
            row=next(r for r in rows if r['run_id']==f'resident-{block}-{mode}')
            pair[mode]=stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])
        summary['pairs'].append({'block':block,'compute_seconds':pair,'retained_minus_control_median_seconds':pair['retained']['median']-pair['control']['median']})
    control=summary['modes']['control']['stages_seconds']['compute_ns'];retained=summary['modes']['retained']['stages_seconds']['compute_ns']
    summary['local_warm_acceptance']=all(p['retained_minus_control_median_seconds']<0 for p in summary['pairs']) and retained['median']<control['median'] and retained['p95']<control['p95']
    save(args.output/'summary.json',summary);print('COMPLETE',flush=True)


if __name__=='__main__':
    main()
