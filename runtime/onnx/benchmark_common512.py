"""Paired one-thread common-shape operating-configuration pilot, not backend isolation."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import random

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
    index = json.loads((prior/'file-index.json').read_text(encoding='utf-8'))
    for item in index:
        if sha(prior/item['path']) != item['sha256']:
            raise ValueError('archived length evidence changed')
    oracle = json.loads((prior/'oracle-oracle.json').read_text(encoding='utf-8'))
    length_pre = json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    old = json.loads((ROOT/'docs/research/jeff-onnx-tract/performance-pilot-2026-10-10/primary/preregistration.json').read_text(encoding='utf-8'))
    native = ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe'
    tract = ROOT/'.venv/tract-scatter-target/release/bench.exe'
    model = ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'
    generation = ROOT/'.venv/tract-scatter-candidate/generation.json'
    native_hash = next(a['sha256'] for a in old['assets'] if a['path'].endswith('kaze_judge_native_bench.exe'))
    assets = [(native,native_hash),(tract,length_pre['executable_sha256']),
              (model,length_pre['model_sha256']),(generation,length_pre['generation_sha256'])]
    assets += [(manifest,next(a['sha256'] for a in old['assets'] if a['path'].endswith('jeff-rust-bundle-p3.json')))]
    native_manifest = json.loads(manifest.read_text(encoding='utf-8'))
    native_root = manifest.parent/native_manifest['checkpoint_dir']
    assets += [(native_root/a['path'],a['sha256']) for a in native_manifest['files']]
    assets += [(generation.parent/a['path'],a['sha256']) for a in json.loads(generation.read_text(encoding='utf-8'))['files']]
    baseline = json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
    differences = [a['path'] for a in baseline if sha(ROOT/a['path']) != a['sha256']]
    if differences != ['.gitignore']:
        raise ValueError('native reference changed')
    for path,expected in assets:
        if sha(path) != expected:
            raise ValueError(f'frozen asset changed: {path}')
    if not oracle['passed'] or native_manifest['policy']['cpu_threads'] != 1:
        raise ValueError('accepted oracle and fixed one-thread Native policy required')
    cases = oracle['cases'][:4] + [x for x in oracle['cases'][4:] if x['tokens']==512 and x['candidate_count']!=8]
    if len(cases)!=8 or any(x['tokens']!=512 for x in cases[4:]):
        raise ValueError('four goldens and four common-shape inputs required')
    for case in cases:
        case['count'] = len(case['request']['candidates'])
    for case in cases[4:]:
        if (len(case['inputs']['input_ids'])!=512 or case['inputs']['attention_mask']!=[1]*512
                or case['inputs']['mm_token_type_ids']!=[0]*512):
            raise ValueError('common shape requires no padding, text only')
    tract_refs = {e['case']:e['raw_logits'] for e in [json.loads(line) for line in
        (prior/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    orders = [['native','tract'],['tract','native'],['native','tract']]
    schedules=[]
    for block in range(3):
        measured=list(range(4,8))
        random.Random(20261012+block).shuffle(measured)
        schedules.append([{'case':4+block,'warmup':True}]+[{'case':i,'warmup':False} for i in measured])
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'preregistration.json',{'date_utc':datetime.now(timezone.utc).isoformat(),
        'script_sha256':sha(__file__),'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'),
        'oracle_sha256':sha(prior/'oracle-oracle.json'),'previous_raw_sha256':sha(prior/'gate.stdout.jsonl'),
        'assets':[{'path':p.relative_to(ROOT).as_posix(),'sha256':h} for p,h in assets],
        'orders':orders,'schedules':schedules,'threads':1,'effective_tokens':512,'physical_tokens':512,
        'gate_inputs':8,'sessions_per_backend':3,'warmups_per_session':1,'measured_per_session':4,
        'samples_per_backend':12,'seed':20261012,'timeout_seconds':600,'memory_limit_bytes':limit,
        'available_physical_bytes':memory.ullAvailPhys,'formal_slo_acceptance':False,
        'numerical_acceptance':'probability maxabs <=1e-4, sum error <=1e-6, judgment/tokens exact; Native probabilities and Tract raw logits exactly repeat gate; Tract raw exactly prior four-thread gate',
        'comparison_scope':'common512 one-thread operating configurations; Native backbone+head/softmax vs Tract forward+score; not runtime-only effect',
        'performance_acceptance':'descriptive paired pilot; no backend adoption or speedup claim',
        'limitations':['Native BF16 mmap/per-forward FP32 conversion vs Tract retained FP32 packed plan',
            'Native serial DeltaNet recurrence vs exported graph algorithm',
            'Native head+softmax combined, Tract head inside forward; kernel boundaries differ',
            'Native tokenizer/policy/request vs Tract prepared request are not matched E2E',
            'Native startup verifies bundle/tokenizer, Tract asset preflight excluded; startup/peak incidental n=3',
            'n=12 p95=max, only three independent pairs; one warmup; artificial content, no quality labels',
            'thermals/affinity/background load/storage cache uncontrolled; hashes preflighted before timing']})
    records=[]
    native_refs={}
    def run(backend,run_id,schedule,gate=False):
        job=args.output/(run_id+'.job.json')
        save(job,{'mode':'nnef-decluttered','threads':1,'profile_codegen':False,'profile_forward':False,
            'cases':cases,'schedule':schedule})
        print('START',run_id,flush=True)
        exe,asset=(native,manifest) if backend=='native' else (tract,model)
        row=invoke([exe.resolve(),asset.resolve(),job.resolve()],args.output,run_id,limit)
        events=[json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events,cases,native_manifest['policy'],expected_threads=1)
        if len(events)!=len(schedule)+2:
            raise ValueError('event count mismatch')
        if backend=='tract' and (events[0]['executor_threads']!=1 or not events[0]['multithread_mm']):
            raise ValueError('Tract executor mismatch')
        for event,item in zip(events[1:-1],schedule):
            case=cases[item['case']]
            expected_physical=case['tokens'] if backend=='native' else 512
            if event['case']!=case['id'] or event['warmup']!=item['warmup'] or event['physical_tokens']!=expected_physical:
                raise ValueError('schedule/shape mismatch')
            if backend=='tract':
                if event['forward_profile'] or event['raw_logits']!=tract_refs[event['case']]:
                    raise ValueError('Tract raw/profile mismatch')
                event['compute_ns']=event['forward_ns']+event['score_ns']
            else:
                if gate:
                    native_refs[event['case']]=event['probabilities']
                elif event['probabilities']!=native_refs[event['case']]:
                    raise ValueError('Native probability repeat mismatch')
                event['compute_ns']=event['backbone_ns']+event['head_softmax_ns']
        row.update(backend=backend,events=events)
        save(args.output/(run_id+'.validated.json'),row)
        records.append(row)
        print('DONE',run_id,'forwards',len(schedule),flush=True)
    gate=[{'case':i,'warmup':False} for i in range(8)]
    run('native','gate-native',gate,True)
    run('tract','gate-tract',gate,True)
    for block,order in enumerate(orders):
        for backend in order:
            run(backend,f'resident-{block}-{backend}',schedules[block])
    summary={'formal_slo_acceptance':False,'numerical_gate_passed':True,'processes':len(records),
        'forwards':sum(len(r['events'])-2 for r in records),'backends':{},'pairs':[],
        'max_probability_error':max(e['probability_max_abs_error'] for r in records for e in r['events'][1:-1])}
    for backend in ['native','tract']:
        resident=[r for r in records if r['backend']==backend and r['run_id'].startswith('resident')]
        es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        keys=['compute_ns','request_ns']+(['tokenize_ns','backbone_ns','head_softmax_ns','policy_ns'] if backend=='native' else ['prepare_ns','forward_ns','score_ns'])
        summary['backends'][backend]={'stages_seconds':{key:stats([e[key]/1e9 for e in es]) for key in keys},
            'startup_seconds':stats([r['events'][0]['startup_ns']/1e9 for r in resident]),
            'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs':{case['id']:stats([e['compute_ns']/1e9 for e in es if e['case']==case['id']]) for case in cases[4:]}}
    for block in range(3):
        pair={}
        for backend in ['native','tract']:
            row=next(r for r in records if r['run_id']==f'resident-{block}-{backend}')
            pair[backend]=stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])
        summary['pairs'].append({'block':block,'compute_seconds':pair,
            'tract_minus_native_session_median_seconds':pair['tract']['median']-pair['native']['median']})
    save(args.output/'summary.json',summary)
    print('COMPLETE',flush=True)


if __name__=='__main__':
    main()
