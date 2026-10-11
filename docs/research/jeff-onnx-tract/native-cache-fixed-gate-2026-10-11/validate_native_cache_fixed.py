"""Full 28-case numerical gate with frozen explicit cache initialization; not timing."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, validate_events
from diagnose_native_cache import delta, f32
from diagnose_native_repeats import host_state


def check_events(events, cases, schedule, configuration, policy, old, refs, first):
    validate_events(events, cases, policy, expected_threads=4)
    if len(events) != len(schedule)+2:
        raise ValueError('event count mismatch')
    init = events[0]
    if init['cache_diagnostic'] != configuration:
        raise ValueError('cache initialization/affinity restoration mismatch')
    if (init['requested_threads'], init['rayon_pool_threads'], init['candle_env_threads'],
            init['expected_barrier_aux_workers'], init['manifest_cpu_threads']) != (4,4,'4',3,1):
        raise ValueError('pool configuration mismatch')
    if not init['retained_f32'] or (init['cached_tensors'], init['cached_bytes'],
            init['head_cached_tensors'], init['head_cached_bytes']) != (320,3009572096,1,1044480):
        raise ValueError('FP32 retention mismatch')
    for e, item in zip(events[1:-1], schedule):
        case = cases[item['case']]
        if e['case'] != case['id'] or e['warmup'] or e['physical_tokens'] != case['tokens']:
            raise ValueError('schedule/shape mismatch')
        expected = [t for t, active in zip(case['inputs']['input_ids'], case['inputs']['attention_mask']) if active]
        if e['input_ids'] != expected:
            raise ValueError('input IDs mismatch')
        for key, n in [('hidden_values',1024), ('raw_logits',255)]:
            if len(e[key]) != n or not all(math.isfinite(x) for x in e[key]):
                raise ValueError('nonfinite or wrong-size diagnostic vector')
        if not all(configuration['process_allowed_mask'] & (1 << e[key]) for key in ['processor_before','processor_after']):
            raise ValueError('processor outside original mask')
        old_error = delta(e['probabilities'], old[e['case']])
        native_error = delta(e['probabilities'], refs[e['case']]) if e['case'] in refs else None
        previous = first.get(e['case'])
        repeat_error = delta(e['probabilities'], previous['probabilities']) if previous else 0.0
        if old_error > 1e-6 or repeat_error > 1e-6 or (native_error is not None and native_error > 1e-4):
            raise ValueError(f"unchanged Native numeric gate failed: {e['case']} old={old_error} repeat={repeat_error} native={native_error}")
        e.update(old_gate_probability_error=old_error, cross_process_probability_error=repeat_error,
            frozen_native_probability_error=native_error)
        first.setdefault(e['case'], e)


def summarize(rows, cases):
    result = {'processes':len(rows), 'forwards':sum(len(r['events'])-2 for r in rows),
        'all_28_case_numeric_cross_process_gates_passed':True, 'cache_configuration':'cacheB',
        'repeat_threshold':1e-6, 'performance_acceptance':False, 'formal_slo_acceptance':False,
        'production_backend_acceptance':False, 'cases':{}}
    for case in cases:
        es = [e for r in rows for e in r['events'][1:-1] if e['case']==case['id']]
        if len(es) != 2:
            raise ValueError('two independent process observations per case required')
        a,b = es
        result['cases'][case['id']] = {'tokens':case['tokens'], 'observations':2,
            'probabilities_exact':a['probabilities']==b['probabilities'],
            'hidden_exact':a['hidden_values']==b['hidden_values'], 'raw_exact':a['raw_logits']==b['raw_logits'],
            'cross_process_probability_error':delta(a['probabilities'],b['probabilities']),
            'hidden_cross_process_error':delta(f32(a['hidden_values']),f32(b['hidden_values'])),
            'raw_cross_process_error':delta(f32(a['raw_logits']),f32(b['raw_logits'])),
            'max_old_gate_error':max(e['old_gate_probability_error'] for e in es),
            'max_onnx_error':max(e['probability_max_abs_error'] for e in es)}
    result['max_onnx_error'] = max(v['max_onnx_error'] for v in result['cases'].values())
    result['max_old_gate_error'] = max(v['max_old_gate_error'] for v in result['cases'].values())
    result['max_cross_process_probability_error'] = max(v['cross_process_probability_error'] for v in result['cases'].values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    prior = ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
    failure = ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
    for directory in [prior, failure]:
        for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/a['path']) != a['sha256']:
                raise ValueError('previous archive changed')
    pre = json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    for a in pre['assets']:
        if sha(ROOT/a['path']) != a['sha256']:
            raise ValueError('frozen asset changed')
    exe = ROOT/'.venv/native-cache-diagnostic-target/release/native_cache_diagnostic.exe'
    gen = ROOT/'.venv/native-cache-diagnostic-v2/generation.json'
    if sha(exe) != pre['executable_sha256'] or sha(gen) != pre['generation_sha256']:
        raise ValueError('frozen diagnostic exe/source changed')
    for a in json.loads(gen.read_text(encoding='utf-8'))['files']:
        if sha(gen.parent/a['path']) != a['sha256']:
            raise ValueError('generated source changed')
    cases = json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
    old = json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
    refs = json.loads((ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11/previous-native-probabilities.json').read_text(encoding='utf-8'))
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'; policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    config = pre['configurations']['cacheB']
    if len(cases) != 28 or len({v['id'] for v in cases}) != 28 or set(old) != {v['id'] for v in cases} or policy['cpu_threads'] != 1:
        raise ValueError('fixed 28 cases and old references required')
    # Fixed chunking bounds individual children under their existing 600s deadline.
    chunks = [list(range(i,i+7)) for i in range(0,28,7)]; runs = []
    for round_id, order in enumerate([[0,1,2,3],[3,2,1,0]]):
        for chunk in order:
            indices = chunks[chunk].copy(); random.Random(5781113+10*round_id+chunk).shuffle(indices)
            runs.append({'id':f'gate-{round_id}-chunk{chunk}', 'round':round_id, 'chunk':chunk,
                'schedule':[{'case':i,'warmup':False} for i in indices]})
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, memory.ullTotalPhys//2); args.output.mkdir(parents=True,exist_ok=False)
    invoke([exe.resolve(),'--cache-probe',str(config['requested_cpu'])],args.output,'cache-probe',limit,timeout=30)
    actual = json.loads((args.output/'cache-probe.stdout.jsonl').read_text(encoding='utf-8'))
    if actual != config:
        raise ValueError('registered cache condition unavailable on this host')
    sources = ['runtime/onnx/validate_native_cache_fixed.py','runtime/onnx/benchmark_pilot.py',
        'runtime/onnx/diagnose_native_cache.py','runtime/onnx/diagnose_native_repeats.py']
    save(args.output/'preregistration.json', {'utc':datetime.now(timezone.utc).isoformat(),
        'sources':[{'path':p,'sha256':sha(ROOT/p)} for p in sources],
        'assets':pre['assets'], 'executable_sha256':sha(exe),'generation_sha256':sha(gen),
        'prior_cache_archive_index_sha256':sha(prior/'file-index.json'),
        'failure_archive_index_sha256':sha(failure/'file-index.json'),
        'cases_sha256':sha(failure/'reference-cases.json'), 'old_gate_sha256':sha(failure/'native-length-gate-probabilities.json'),
        'native_refs_sha256':sha(ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11/previous-native-probabilities.json'),
        'configuration':config,'runs':runs,'seed':5781113,'case_ids':[v['id'] for v in cases],
        'processes':8,'forwards':56,'observations_per_case':2,'threads':4,
        'timeout_seconds':600,'memory_limit_bytes':limit,'host_before':host_state(),
        'acceptance':'ONNX maxabs<=1e-4,sum<=1e-6,judgment/tokens exact; old 28-case Native4 gate<=1e-6; cross-process same-case<=1e-6; frozen Native references<=1e-4 where available; input IDs exact, finite hidden1024/raw255; recorded cache/pool/resource exact',
        'scope':'same frozen instrumented exe; only cacheB initialization job parameter fixed, main affinity restored before pool/model/forward',
        'performance_acceptance':False,'formal_slo_acceptance':False,'production_backend_acceptance':False,
        'limitations':['two observations per case in separate chunked processes; no all-case within-process repeats or long resident history',
            'same 28 artificial inputs, not held-out inputs or labeled recognition quality',
            'instrumented exe; not uninstrumented performance build acceptance',
            'initial cache condition fixed; compute core placement/temperature/frequency/background not controlled',
            'CPU index0/cacheB valid only for this verified host; no portable core-selection policy',
            'timings diagnostic only; old failed run and thresholds unchanged']})
    first = {}; rows = []; active = None
    try:
        for run in runs:
            active = run['id']; job = args.output/(active+'.job.json')
            save(job, {'threads':4,'retained_f32':True,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':run['schedule']})
            print('START',active,flush=True); before = host_state()
            row = invoke([exe.resolve(),manifest.resolve(),job.resolve()],args.output,active,limit); after = host_state()
            events = [json.loads(line) for line in (args.output/(active+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
            check_events(events,cases,run['schedule'],config,policy,old,refs,first)
            row.update(events=events,round=run['round'],chunk=run['chunk'],host_before=before,host_after=after)
            save(args.output/(active+'.validated.json'),row); rows.append(row)
            print('DONE',active,'forwards',len(events)-2,flush=True)
        save(args.output/'summary.json',summarize(rows,cases));print('COMPLETE',flush=True)
    except Exception as error:
        save(args.output/'failure.json',{'active_run':active,'completed_runs':[r['run_id'] for r in rows],
            'error_type':type(error).__name__,'error':str(error),'host_after':host_state(),
            'numeric_acceptance':False,'performance_acceptance':False})
        raise


if __name__ == '__main__':
    main()
