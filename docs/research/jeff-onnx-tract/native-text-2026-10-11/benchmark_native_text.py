"""Paired full473/text320 Native FP32 retention memory pilot."""
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
    previous=ROOT/'docs/research/jeff-onnx-tract/native-retained-2026-10-11'
    for item in json.loads((previous/'file-index.json').read_text(encoding='utf-8')):
        if sha(previous/item['path'])!=item['sha256']:raise ValueError('full-cache evidence changed')
    old=json.loads((previous/'preregistration.json').read_text(encoding='utf-8'))
    cases=json.loads((previous/'reference-cases.json').read_text(encoding='utf-8'))
    refs=json.loads((previous/'previous-native-probabilities.json').read_text(encoding='utf-8'))
    generation=ROOT/'.venv/native-text-candidate/generation.json'
    generated=json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path'])!=item['sha256']:raise ValueError('generated candidate changed')
    for path,digest in generated['sources'].items():
        if sha(ROOT/path)!=digest:raise ValueError('source changed')
    if sha(ROOT/'runtime/onnx/prepare_native_text.py')!=generated['generator_sha256']:raise ValueError('generator changed')
    full=ROOT/'.venv/native-retained-target/release/native_retained_bench.exe'
    text=ROOT/'.venv/native-text-target/release/native_retained_bench.exe'
    if sha(full)!=old['executable_sha256']:raise ValueError('full-cache executable changed')
    for item in old['assets']:
        if sha(ROOT/item['path'])!=item['sha256']:raise ValueError('fixed Native asset changed')
    manifest=ROOT/'models/jeff-rust-bundle-p3.json'
    policy=json.loads(manifest.read_text(encoding='utf-8'))['policy']
    orders=[['full','text'],['text','full'],['full','text']]
    schedules=[]
    for block in range(3):
        measured=list(range(4,8));random.Random(320473+block).shuffle(measured)
        schedules.append([{'case':4+block,'warmup':True}]+[{'case':i,'warmup':False} for i in measured])
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys<4*1024**3:raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),
        'script_sha256':sha(__file__),'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'),
        'full_executable_sha256':sha(full),'text_executable_sha256':sha(text),'generation_sha256':sha(generation),
        'previous_generation_sha256':sha(previous/'generation.json'),'assets':old['assets'],
        'reference_cases_sha256':sha(previous/'reference-cases.json'),'previous_native_probabilities_sha256':sha(previous/'previous-native-probabilities.json'),
        'orders':orders,'schedules':schedules,'seed':320473,'threads':1,'physical_tokens':512,'effective_tokens':512,
        'sessions_per_mode':3,'warmups_per_session':1,'samples_per_session':4,'samples_per_mode':12,'gate_cases_per_mode':8,
        'timeout_seconds':600,'memory_limit_bytes':limit,'available_physical_bytes':memory.ullAvailPhys,
        'numerical_acceptance':'probability/judgment/tokens gates and all probabilities exactly equal frozen Native gate',
        'memory_acceptance':'local memory-only iff all three paired lifetime peaks and pooled maximum decrease; numeric/resource gates pass',
        'latency_acceptance':'descriptive only; no speedup or noninferiority acceptance',
        'formal_slo_acceptance':False,'scope':'full473 vs text320 owned FP32, same equations/wrapper/dependencies, head1 retained both',
        'limitations':['synthetic four inputs, n=12 p95=max, three independent pairs, one warmup',
            'startup and lifetime peaks n=3 incidental; includes temporary mmap/conversion, not warm private memory',
            'thermals/affinity/background/storage cache uncontrolled; hashes preflighted before timing',
            'no Tract comparison, API E2E, recognition quality or product API change']})
    rows=[]
    def run(mode,run_id,schedule):
        job=args.output/(run_id+'.job.json')
        save(job,{'retained_f32':True,'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True)
        exe=full if mode=='full' else text
        row=invoke([exe.resolve(),manifest.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,policy,expected_threads=1)
        init=events[0]
        expected=(473,3411943680) if mode=='full' else (320,3009572096)
        if (len(events)!=len(schedule)+2 or not init['retained_f32']
                or (init['cached_tensors'],init['cached_bytes'])!=expected
                or init['head_cached_tensors']!=1 or init['head_cached_bytes']!=1044480):raise ValueError('cache/schedule mismatch')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            if event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['physical_tokens']!=case['tokens']:raise ValueError('shape/schedule mismatch')
            if event['probabilities']!=refs[event['case']]:raise ValueError('Native probability bits changed')
            event['compute_ns']=event['backbone_ns']+event['head_softmax_ns']
        row.update(mode=mode,events=events)
        save(args.output/(run_id+'.validated.json'),row);rows.append(row)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    gate=[{'case':i,'warmup':False} for i in range(8)]
    run('full','gate-full',gate);run('text','gate-text',gate)
    for block,order in enumerate(orders):
        for mode in order:run(mode,f'resident-{block}-{mode}',schedules[block])
    summary={'processes':len(rows),'forwards':sum(len(r['events'])-2 for r in rows),'numeric_passed':True,
        'probabilities_exact_to_frozen_native':True,'formal_slo_acceptance':False,
        'max_probability_error':max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),'modes':{},'pairs':[]}
    for mode in ['full','text']:
        resident=[r for r in rows if r['mode']==mode and r['run_id'].startswith('resident')]
        es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        summary['modes'][mode]={'stages_seconds':{k:stats([e[k]/1e9 for e in es]) for k in ['compute_ns','backbone_ns','head_softmax_ns','tokenize_ns','policy_ns','request_ns']},
            'startup_seconds':stats([r['events'][0]['startup_ns']/1e9 for r in resident]),
            'retention_load_seconds':stats([r['events'][0]['retention_load_ns']/1e9 for r in resident]),
            'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs':{case['id']:stats([e['compute_ns']/1e9 for e in es if e['case']==case['id']]) for case in cases[4:]}}
    for block in range(3):
        pair={};peaks={}
        for mode in ['full','text']:
            row=next(r for r in rows if r['run_id']==f'resident-{block}-{mode}')
            pair[mode]=stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']]);peaks[mode]=row['peak_working_set_bytes']
        summary['pairs'].append({'block':block,'compute_seconds':pair,'peak_working_set_bytes':peaks,
            'text_minus_full_median_seconds':pair['text']['median']-pair['full']['median'],
            'text_minus_full_peak_bytes':peaks['text']-peaks['full']})
    summary['local_memory_acceptance']=all(p['text_minus_full_peak_bytes']<0 for p in summary['pairs']) and summary['modes']['text']['peak_working_set_bytes']['max']<summary['modes']['full']['peak_working_set_bytes']['max']
    save(args.output/'summary.json',summary);print('COMPLETE',flush=True)


if __name__=='__main__':
    main()
