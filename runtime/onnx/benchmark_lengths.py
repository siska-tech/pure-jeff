"""Numerical-gated four-thread input-length pilot on the accepted frozen binary."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    previous = ROOT/'docs/research/jeff-onnx-tract/accepted-threads-2026-10-11'
    frozen = json.loads((previous/'preregistration.json').read_text(encoding='utf-8'))
    exe = ROOT/'.venv/tract-scatter-target/release/bench.exe'
    generation = ROOT/'.venv/tract-scatter-candidate/generation.json'
    model = ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
    for path,expected in [(exe,frozen['executable_sha256']),(generation,frozen['generation_sha256']),(model,frozen['model_sha256'])]:
        if sha(path) != expected:
            raise ValueError('frozen asset changed')
    generated = json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path']) != item['sha256']:
            raise ValueError('generated source changed')
    oracle = json.loads(args.oracle.read_text(encoding='utf-8'))
    opre = json.loads((args.oracle.parent/'preregistration.json').read_text(encoding='utf-8'))
    process = json.loads((args.oracle.parent/'oracle.process.json').read_text(encoding='utf-8'))
    if not oracle['passed'] or process['exit_code'] or process['guard_trigger'] is not None:
        raise ValueError('successful guarded oracle required')
    fixture = previous/'length-inputs.json'
    data = json.loads(fixture.read_text(encoding='utf-8'))
    if sha(fixture) != oracle['fixture_sha256'] or oracle['model_sha256'] != opre['model_sha256']:
        raise ValueError('oracle fixture/model mismatch')
    if sha(ROOT/'runtime/onnx/prepare_length_oracle.py') != opre['script_sha256']:
        raise ValueError('oracle harness changed')
    cases = oracle['cases']
    if len(cases) != 28:
        raise ValueError('4 goldens plus 24 length cases required')
    for case,original in zip(cases[4:],data['cases']):
        if any(case[key] != value for key,value in original.items()):
            raise ValueError('length case changed')
    for case in cases:
        count=len(case['request']['candidates'])
        if not 2 <= count <= 255 or case.get('count',count) != count or case.get('candidate_count',count) != count:
            raise ValueError('candidate count mismatch')
        case['count']=count
    refs = {e['case']:e['raw_logits'] for e in [json.loads(line) for line in
        (previous/'gate-4.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    primary = [i for i,case in enumerate(cases) if 'variant' in case and case['candidate_count'] != 8]
    lengths = [128,256,384,511,512]
    if len(primary) != 20 or any(sum(cases[i]['tokens']==length for i in primary)!=4 for length in lengths):
        raise ValueError('primary coverage mismatch')
    schedules=[]
    variants=sorted({cases[i]['variant'] for i in primary})
    for block in range(3):
        warm = [next(i for i in primary if cases[i]['tokens']==length and cases[i]['variant']==variants[block]) for length in lengths]
        measured=primary.copy()
        random.Random(20261011+block).shuffle(measured)
        schedules.append([{'case':i,'warmup':True} for i in warm]+[{'case':i,'warmup':False} for i in measured])
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),
        'executable_sha256':sha(exe),'generation_sha256':sha(generation),'model_sha256':sha(model),
        'fixture_sha256':sha(fixture),'oracle_sha256':sha(args.oracle),'script_sha256':sha(__file__),
        'threads':4,'profile_enabled':False,'sessions':3,'warmups_per_session':5,'measured_per_session':20,
        'lengths':lengths,'variants_per_length':4,'samples_per_length':12,'schedules':schedules,
        'gate_cases':28,'extra_eight_candidate_cases_gate_only':4,'seed':20261011,
        'numerical_acceptance':'finite raw255; probability maxabs <=1e-4; sum error <=1e-6; judgment/tokens exact; repeated raw logits exact to Tract gate',
        'performance_acceptance':'descriptive pilot only; no speedup or SLO acceptance',
        'formal_slo_acceptance':False,'timeout_seconds':600,'memory_limit_bytes':limit,
        'available_physical_bytes':memory.ullAvailPhys,'scope':'same step1113 FP32 batch1 physical512; prepared tensors',
        'limitations':['n=12 nearest-rank p95 is max; four inputs and three sessions, not 12 independent sessions',
            'length and content confounded; primary candidate counts 2/3; eight-candidate extras excluded from timing',
            'thermals, affinity, background load and storage cache uncontrolled',
            'no Native, tokenizer/API E2E, recognition quality or cold campaign']})
    records=[]
    tract_refs={}
    def run(run_id,schedule,gate=False):
        job=args.output/(run_id+'.job.json')
        save(job,{'mode':'nnef-decluttered','profile_codegen':False,'profile_forward':False,'threads':4,'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True)
        record=invoke([exe.resolve(),model.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,policy,expected_threads=4)
        if len(events)!=len(schedule)+2 or events[0]['executor_threads']!=4 or not events[0]['multithread_mm']:
            raise ValueError('executor/schedule mismatch')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            raw=event['raw_logits']
            if (event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['forward_profile']
                or len(raw)!=255 or not all(math.isfinite(v) for v in raw)):
                raise ValueError('schedule/profile/raw mismatch')
            if case['id'] in refs and raw!=refs[case['id']]:
                raise ValueError('existing golden raw changed')
            if gate:
                tract_refs[case['id']]=raw
            elif raw!=tract_refs[case['id']]:
                raise ValueError('repeated raw logits differ')
            event['onnx_raw_max_abs_error']=max(abs(x-y) for x,y in zip(raw,case['reference_raw_logits']))
        record.update(events=events)
        save(args.output/(run_id+'.validated.json'),record)
        records.append(record)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    run('gate',[{'case':i,'warmup':False} for i in range(28)],True)
    for block,schedule in enumerate(schedules):
        run(f'resident-{block}',schedule)
    resident=records[1:]
    measured=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    summary={'formal_slo_acceptance':False,'numerical_gate_passed':True,'repeated_raw_logits_exact':True,
        'processes':len(records),'forwards':sum(len(r['events'])-2 for r in records),
        'max_probability_error':max(e['probability_max_abs_error'] for r in records for e in r['events'][1:-1]),
        'onnx_raw_max_abs_error':max(e['onnx_raw_max_abs_error'] for r in records for e in r['events'][1:-1]),
        'startup_seconds':stats([r['events'][0]['startup_ns']/1e9 for r in resident]),
        'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),'lengths':{},'inputs':{}}
    for length in lengths:
        es=[e for e in measured if e['effective_tokens']==length]
        summary['lengths'][str(length)]={key:stats([e[key]/1e9 for e in es]) for key in ['prepare_ns','forward_ns','score_ns','request_ns']}
    for i in primary:
        es=[e for e in measured if e['case']==cases[i]['id']]
        summary['inputs'][cases[i]['id']]={'tokens':cases[i]['tokens'],'variant':cases[i]['variant'],
            'candidate_count':cases[i]['candidate_count'],'forward_seconds':stats([e['forward_ns']/1e9 for e in es])}
    save(args.output/'summary.json',summary)
    print('COMPLETE',flush=True)


if __name__=='__main__':
    main()
