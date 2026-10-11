"""Native text320 FP32 thread matrix, balanced four-session descriptive pilot."""
import argparse
import ctypes as c
from datetime import datetime,timezone
import json
from pathlib import Path
import random
from benchmark_pilot import ROOT,MemoryStatus,invoke,save,sha,stats,validate_events


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    prior=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11'
    for item in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):
        if sha(prior/item['path'])!=item['sha256']:raise ValueError('frozen text evidence changed')
    old=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    cases=json.loads((prior/'reference-cases.json').read_text(encoding='utf-8'))
    refs=json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'))
    generation=ROOT/'.venv/native-threads-candidate/generation.json';generated=json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path'])!=item['sha256']:raise ValueError('generated source changed')
    for p,h in generated['sources'].items():
        if sha(ROOT/p)!=h:raise ValueError('original source changed')
    if sha(ROOT/'runtime/onnx/prepare_native_threads.py')!=generated['generator_sha256']:raise ValueError('generator changed')
    if sha(ROOT/'runtime/onnx/prepare_native_retained.py')!=generated['anchor_helper_sha256']:raise ValueError('anchor helper changed')
    for item in old['assets']:
        if sha(ROOT/item['path'])!=item['sha256']:raise ValueError('Native asset changed')
    if sha(ROOT/'.venv/native-text-target/release/native_retained_bench.exe')!=old['text_executable_sha256']:raise ValueError('old executable changed')
    audit=ROOT/'docs/research/jeff-onnx-tract/fp32-common512-2026-10-11/thread-audit.json'
    for item in json.loads(audit.read_text(encoding='utf-8'))['sources'].values():
        if sha(item['path'])!=item['sha256']:raise ValueError('audited dependency/source changed')
    exe=ROOT/'.venv/native-threads-target/release/native_retained_bench.exe';manifest=ROOT/'models/jeff-rust-bundle-p3.json'
    policy=json.loads(manifest.read_text(encoding='utf-8'))['policy']
    orders=[[1,2,4,8],[2,8,1,4],[4,1,8,2],[8,4,2,1]]
    schedules=[]
    for block in range(4):
        measured=list(range(4,8));random.Random(1248320+block).shuffle(measured)
        schedules.append([{'case':4+block,'warmup':True}]+[{'case':i,'warmup':False} for i in measured])
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys<4*1024**3:raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),'script_sha256':sha(__file__),
        'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'),'executable_sha256':sha(exe),'generation_sha256':sha(generation),
        'audit_sha256':sha(audit),'assets':old['assets'],'reference_cases_sha256':sha(prior/'reference-cases.json'),
        'native_probabilities_sha256':sha(prior/'previous-native-probabilities.json'),'orders':orders,'schedules':schedules,
        'threads':[1,2,4,8],'seed':1248320,'sessions_per_setting':4,'warmups_per_session':1,'samples_per_session':4,'samples_per_setting':16,
        'gate_cases_per_setting':8,'physical_tokens':512,'effective_tokens':512,'timeout_seconds':600,'memory_limit_bytes':limit,
        'available_physical_bytes':memory.ullAvailPhys,'formal_slo_acceptance':False,
        'numerical_acceptance':'all ONNX probability maxabs<=1e-4,sum<=1e-6,judgment/tokens gates; fixed Native maxabs<=1e-4; one-thread exact; per-setting gate repeat maxabs<=1e-6',
        'performance_acceptance':'descriptive pilot; next candidate only if all four block medians and pooled median/p95 below one-thread, select lowest pooled median among eligible; no adoption/SLO',
        'scope':'same new executable, text320/head1 owned FP32; only requested compute threads change; DeltaNet serial',
        'limitations':['four independent blocks, n=16 p95=max, one warmup, synthetic requests, no recognition labels',
            'Williams balanced order; thermals/affinity/background/storage cache uncontrolled',
            'reported actual global Rayon pool size/configured GEMM setting; no active worker telemetry or OS-thread cap',
            'Candle barrier auxiliary worker count is derived expectation, not observed count; helper pools may coexist',
            'startup/lifetime peak n=4 incidental, not cold campaign/private warm memory/API E2E/Tract comparison']})
    rows=[];gate_refs={}
    def run(threads,run_id,schedule,gate=False):
        job=args.output/(run_id+'.job.json');save(job,{'threads':threads,'retained_f32':True,'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True);row=invoke([exe.resolve(),manifest.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,policy,expected_threads=threads);init=events[0]
        if (len(events)!=len(schedule)+2 or init['requested_threads']!=threads or init['rayon_pool_threads']!=threads
                or init['candle_env_threads']!=str(threads) or init['expected_barrier_aux_workers']!=threads-1 or init['manifest_cpu_threads']!=1
                or not init['retained_f32'] or (init['cached_tensors'],init['cached_bytes'])!=(320,3009572096)
                or (init['head_cached_tensors'],init['head_cached_bytes'])!=(1,1044480)):raise ValueError('configuration/cache mismatch')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            if event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['physical_tokens']!=case['tokens']:raise ValueError('schedule mismatch')
            delta=max(abs(a-b) for a,b in zip(event['probabilities'],refs[event['case']]))
            if delta>1e-4 or (threads==1 and event['probabilities']!=refs[event['case']]):raise ValueError('frozen Native gate failed')
            if gate:gate_refs[(threads,event['case'])]=event['probabilities']
            repeat=max(abs(a-b) for a,b in zip(event['probabilities'],gate_refs[(threads,event['case'])]))
            if repeat>1e-6:raise ValueError('per-setting repeat failed')
            event.update(native_probability_max_abs_error=delta,repeat_probability_max_abs_error=repeat,
                compute_ns=event['backbone_ns']+event['head_softmax_ns'])
        row.update(threads=threads,events=events);save(args.output/(run_id+'.validated.json'),row);rows.append(row)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    gate=[{'case':i,'warmup':False} for i in range(8)]
    for threads in [1,2,4,8]:run(threads,f'gate-{threads}',gate,True)
    for block,order in enumerate(orders):
        for threads in order:run(threads,f'resident-{block}-{threads}',schedules[block])
    all_events=[e for r in rows for e in r['events'][1:-1]]
    summary={'processes':len(rows),'forwards':len(all_events),'numerical_passed':True,'formal_slo_acceptance':False,
        'max_onnx_probability_error':max(e['probability_max_abs_error'] for e in all_events),
        'max_native_probability_error':max(e['native_probability_max_abs_error'] for e in all_events),
        'max_repeat_probability_error':max(e['repeat_probability_max_abs_error'] for e in all_events),'settings':{},'blocks':[]}
    for threads in [1,2,4,8]:
        resident=[r for r in rows if r['threads']==threads and r['run_id'].startswith('resident')]
        es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        summary['settings'][str(threads)]={'stages_seconds':{k:stats([e[k]/1e9 for e in es]) for k in ['compute_ns','backbone_ns','head_softmax_ns','tokenize_ns','policy_ns','request_ns']},
            'startup_stages_seconds':{k:stats([r['events'][0][k]/1e9 for r in resident]) for k in resident[0]['events'][0] if k.endswith('_ns')},
            'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs':{case['id']:stats([e['compute_ns']/1e9 for e in es if e['case']==case['id']]) for case in cases[4:]}}
    for block in range(4):
        summary['blocks'].append({'block':block,'compute_seconds':{str(t):stats([e['compute_ns']/1e9 for r in rows if r['run_id']==f'resident-{block}-{t}' for e in r['events'][1:-1] if not e['warmup']]) for t in [1,2,4,8]}})
    baseline=summary['settings']['1']['stages_seconds']['compute_ns'];eligible=[]
    for threads in [2,4,8]:
        key=str(threads);candidate=summary['settings'][key]['stages_seconds']['compute_ns']
        if candidate['median']<baseline['median'] and candidate['p95']<baseline['p95'] and all(b['compute_seconds'][key]['median']<b['compute_seconds']['1']['median'] for b in summary['blocks']):eligible.append(threads)
    summary['eligible_next_pilot_threads']=eligible
    summary['next_pilot_threads']=min(eligible,key=lambda t:summary['settings'][str(t)]['stages_seconds']['compute_ns']['median']) if eligible else 1
    save(args.output/'summary.json',summary);print('COMPLETE',flush=True)

if __name__=='__main__':main()
