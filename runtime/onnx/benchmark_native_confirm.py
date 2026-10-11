"""Independent-session Native2/4 confirmation and Tract4 operating comparison."""
import argparse
import ctypes as c
from datetime import datetime,timezone
import itertools
import json
from pathlib import Path
import random
from benchmark_pilot import ROOT,MemoryStatus,invoke,save,sha,stats,validate_events


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    prior=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'
    length=ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
    for directory in [prior,length]:
        for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/item['path'])!=item['sha256']:raise ValueError('previous evidence changed')
    old=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    tract_pre=json.loads((length/'preregistration.json').read_text(encoding='utf-8'))
    cases=json.loads((prior/'reference-cases.json').read_text(encoding='utf-8'))
    refs=json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'))
    tract_refs={e['case']:e['raw_logits'] for e in [json.loads(line) for line in (length/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    native=ROOT/'.venv/native-threads-target/release/native_retained_bench.exe';tract=ROOT/'.venv/tract-scatter-target/release/bench.exe'
    model=ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar';manifest=ROOT/'models/jeff-rust-bundle-p3.json'
    ng=ROOT/'.venv/native-threads-candidate/generation.json';tg=ROOT/'.venv/tract-scatter-candidate/generation.json'
    assets=[(native,old['executable_sha256']),(tract,tract_pre['executable_sha256']),(model,tract_pre['model_sha256']),
        (ng,old['generation_sha256']),(tg,tract_pre['generation_sha256'])]
    assets.extend((ROOT/a['path'],a['sha256']) for a in old['assets'])
    for generation in [ng,tg]:
        assets.extend((generation.parent/a['path'],a['sha256']) for a in json.loads(generation.read_text(encoding='utf-8'))['files'])
    for p,h in assets:
        if sha(p)!=h:raise ValueError(f'frozen asset changed: {p}')
    for item in json.loads((prior/'prior-thread-audit.json').read_text(encoding='utf-8'))['sources'].values():
        if sha(item['path'])!=item['sha256']:raise ValueError('audited source changed')
    policy=json.loads(manifest.read_text(encoding='utf-8'))['policy']
    if len(cases)!=8 or policy['cpu_threads']!=1 or any(case['tokens']!=512 for case in cases[4:]):raise ValueError('fixed cases/policy required')
    for case in cases[4:]:
        if case['inputs']['attention_mask']!=[1]*512 or case['inputs']['mm_token_type_ids']!=[0]*512:raise ValueError('unpadded text only')
    configurations={'native2':2,'native4':4,'tract4':4}
    orders=[list(p) for p in itertools.permutations(configurations)]
    schedules=[]
    for block in range(6):
        measured=list(range(4,8));random.Random(2461113+block).shuffle(measured)
        schedules.append([{'case':4+block%4,'warmup':True}]+[{'case':i,'warmup':False} for i in measured])
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys<4*1024**3:raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),'script_sha256':sha(__file__),
        'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'),'previous_native_preregistration_sha256':sha(prior/'preregistration.json'),
        'reference_cases_sha256':sha(prior/'reference-cases.json'),'native_probabilities_sha256':sha(prior/'previous-native-probabilities.json'),
        'tract_raw_sha256':sha(length/'gate.stdout.jsonl'),'prior_audit_sha256':sha(prior/'prior-thread-audit.json'),
        'assets':[{'path':p.relative_to(ROOT).as_posix(),'sha256':h} for p,h in assets],'configurations':configurations,'orders':orders,'schedules':schedules,
        'seed':2461113,'sessions_per_configuration':6,'samples_per_configuration':24,'warmups_per_session':1,'samples_per_session':4,
        'gate_cases_per_configuration':8,'physical_tokens':512,'effective_tokens':512,'timeout_seconds':600,'memory_limit_bytes':limit,
        'available_physical_bytes':memory.ullAvailPhys,'formal_slo_acceptance':False,
        'numerical_acceptance':'ONNX probability maxabs<=1e-4,sum<=1e-6,judgment/tokens exact; Native frozen maxabs<=1e-4 and per-setting repeat<=1e-6; Tract raw exactly frozen four-thread gate',
        'native4_confirmation':'local warm only iff all six Native4 block medians and pooled median/p95 below Native2; numeric/resource pass',
        'tract_comparison':'descriptive Native4/Tract4 operating configurations, no backend adoption/runtime-only effect/SLO',
        'scope':'new independent sessions and seed after exploratory matrix; same four artificial inputs, not held-out input data',
        'limitations':['n=24 nearest-rank p95=second-largest, six blocks and one warmup; no confidence interval or formal SLO',
            'six permutations balance each configuration position twice; thermal/affinity/background/storage cache uncontrolled',
            'Native text320/head1 FP32 vs Tract FP32 packed plan; algorithms/kernel boundaries differ',
            'Native tokenizer/policy vs Tract prepared tensors; request/startup verification scopes unequal, not API E2E',
            'startup/lifetime peaks n=6 incidental, mapped/shared pages included, not cold campaign/warm private memory',
            'pool size/configuration checked, no active-worker telemetry/OS thread cap; no real OCR/ASR labels']})
    rows=[];gate_refs={}
    def run(configuration,run_id,schedule,gate=False):
        threads=configurations[configuration];is_native=configuration.startswith('native')
        job=args.output/(run_id+'.job.json');save(job,{'threads':threads,'retained_f32':True,'mode':'nnef-decluttered','profile_codegen':False,'profile_forward':False,'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True)
        exe,asset=(native,manifest) if is_native else (tract,model)
        row=invoke([exe.resolve(),asset.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,policy,expected_threads=threads);init=events[0]
        if len(events)!=len(schedule)+2:raise ValueError('event count mismatch')
        if is_native:
            if (init['requested_threads']!=threads or init['rayon_pool_threads']!=threads or init['candle_env_threads']!=str(threads)
                    or init['expected_barrier_aux_workers']!=threads-1 or init['manifest_cpu_threads']!=1 or not init['retained_f32']
                    or (init['cached_tensors'],init['cached_bytes'])!=(320,3009572096)
                    or (init['head_cached_tensors'],init['head_cached_bytes'])!=(1,1044480)):raise ValueError('Native configuration/cache mismatch')
        elif init['executor_threads']!=4 or not init['multithread_mm']:raise ValueError('Tract executor mismatch')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            if event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['physical_tokens']!=(case['tokens'] if is_native else 512):raise ValueError('shape/schedule mismatch')
            if is_native:
                delta=max(abs(a-b) for a,b in zip(event['probabilities'],refs[event['case']]))
                if delta>1e-4:raise ValueError('frozen Native mismatch')
                if gate:gate_refs[(configuration,event['case'])]=event['probabilities']
                repeat=max(abs(a-b) for a,b in zip(event['probabilities'],gate_refs[(configuration,event['case'])]))
                if repeat>1e-6:raise ValueError('Native repeat mismatch')
                event.update(native_probability_max_abs_error=delta,repeat_probability_max_abs_error=repeat,compute_ns=event['backbone_ns']+event['head_softmax_ns'])
            else:
                if event['forward_profile'] or event['raw_logits']!=tract_refs[event['case']]:raise ValueError('Tract raw/profile mismatch')
                event['compute_ns']=event['forward_ns']+event['score_ns']
        row.update(configuration=configuration,events=events);save(args.output/(run_id+'.validated.json'),row);rows.append(row)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    gate=[{'case':i,'warmup':False} for i in range(8)]
    for configuration in configurations:run(configuration,'gate-'+configuration,gate,True)
    for block,order in enumerate(orders):
        for configuration in order:run(configuration,f'resident-{block}-{configuration}',schedules[block])
    es=[e for r in rows for e in r['events'][1:-1]];native_es=[e for r in rows if r['configuration'].startswith('native') for e in r['events'][1:-1]]
    summary={'processes':len(rows),'forwards':len(es),'numerical_passed':True,'formal_slo_acceptance':False,
        'max_onnx_probability_error':max(e['probability_max_abs_error'] for e in es),
        'max_native_probability_error':max(e['native_probability_max_abs_error'] for e in native_es),
        'max_native_repeat_error':max(e['repeat_probability_max_abs_error'] for e in native_es),'configurations':{},'blocks':[]}
    for configuration in configurations:
        resident=[r for r in rows if r['configuration']==configuration and r['run_id'].startswith('resident')];measured=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        keys=['compute_ns','request_ns']+(['backbone_ns','head_softmax_ns','tokenize_ns','policy_ns'] if configuration.startswith('native') else ['forward_ns','score_ns','prepare_ns'])
        summary['configurations'][configuration]={'stages_seconds':{k:stats([e[k]/1e9 for e in measured]) for k in keys},
            'startup_stages_seconds':{k:stats([r['events'][0][k]/1e9 for r in resident]) for k in resident[0]['events'][0] if k.endswith('_ns')},
            'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs':{case['id']:stats([e['compute_ns']/1e9 for e in measured if e['case']==case['id']]) for case in cases[4:]}}
    for block in range(6):
        pair={name:stats([e['compute_ns']/1e9 for r in rows if r['run_id']==f'resident-{block}-{name}' for e in r['events'][1:-1] if not e['warmup']]) for name in configurations}
        summary['blocks'].append({'block':block,'compute_seconds':pair,'native4_minus_native2_median_seconds':pair['native4']['median']-pair['native2']['median'],
            'tract4_minus_native4_median_seconds':pair['tract4']['median']-pair['native4']['median']})
    a=summary['configurations']['native2']['stages_seconds']['compute_ns'];b=summary['configurations']['native4']['stages_seconds']['compute_ns']
    summary['local_native4_confirmation']=all(block['native4_minus_native2_median_seconds']<0 for block in summary['blocks']) and b['median']<a['median'] and b['p95']<a['p95']
    save(args.output/'summary.json',summary);print('COMPLETE',flush=True)

if __name__=='__main__':main()
