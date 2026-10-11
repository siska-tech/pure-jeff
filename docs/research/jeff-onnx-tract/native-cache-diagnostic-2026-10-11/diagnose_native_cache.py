"""Controlled cache-initialization diagnosis; no performance/SLO acceptance."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import struct
import subprocess
from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, validate_events
from diagnose_native_repeats import host_state


def f32(values):
    return [struct.unpack('<f', struct.pack('<f', x))[0] for x in values]


def delta(a, b):
    if len(a) != len(b):
        raise ValueError('vector length mismatch')
    return max(abs(x-y) for x, y in zip(a, b))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    failure = ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
    previous = ROOT/'docs/research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11'
    for directory in [failure, previous]:
        for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/item['path']) != item['sha256']:
                raise ValueError('previous evidence changed')
    old_pre = json.loads((failure/'preregistration.json').read_text(encoding='utf-8'))
    for asset in old_pre['assets']:
        if sha(ROOT/asset['path']) != asset['sha256']:
            raise ValueError('frozen asset changed')
    generation = ROOT/'.venv/native-cache-diagnostic-v2/generation.json'
    generated = json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path']) != item['sha256']:
            raise ValueError('diagnostic source changed')
    validation = json.loads((ROOT/'.venv/native-cache-source-validation.json').read_text(encoding='utf-8'))
    if validation != {'dependency_packages_features_identical':156, 'generated_files_identical':17, 'backbone_unchanged':True, 'weights_unchanged':True}:
        raise ValueError('source/feature validation required')
    exe = ROOT/'.venv/native-cache-diagnostic-target/release/native_cache_diagnostic.exe'
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'; policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    all_cases = json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
    ids = ['synthetic-ocr-ascii-3-128', 'synthetic-asr-unicode-2-512']
    cases = [next(case for case in all_cases if case['id'] == name) for name in ids]
    old = json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
    failed = {e['case']:e['probabilities'] for e in [json.loads(line) for line in
        (failure/'resident-1-native4.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, memory.ullTotalPhys//2)
    args.output.mkdir(parents=True, exist_ok=False)
    kernel = c.WinDLL('kernel32'); kernel.GetCurrentProcess.restype = c.c_void_p
    kernel.GetProcessAffinityMask.argtypes = [c.c_void_p, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
    mask = c.c_size_t(); system = c.c_size_t()
    if not kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), c.byref(mask), c.byref(system)):
        raise OSError('affinity inventory failed')
    inventory = []
    for cpu in range(c.sizeof(c.c_size_t)*8):
        if not mask.value & (1 << cpu):
            continue
        name = f'probe-{cpu}'; invoke([exe.resolve(), '--cache-probe', str(cpu)], args.output, name, limit, timeout=30)
        item = json.loads((args.output/(name+'.stdout.jsonl')).read_text(encoding='utf-8'))
        if item['actual_cpu_at_initialization'] != cpu or not item['affinity_restored'] or item['thread_mask_restored'] != mask.value:
            raise ValueError('probe affinity/restoration mismatch')
        inventory.append(item)
    invalid = subprocess.run([str(exe.resolve()), '--cache-probe', '64'], capture_output=True, timeout=30)
    save(args.output/'invalid-probe.json', {'cpu':64, 'exit_code':invalid.returncode,
        'stdout':invalid.stdout.decode('utf-8'), 'stderr':invalid.stderr.decode('utf-8')})
    if invalid.returncode == 0 or invalid.stdout or b'CPU index exceeds single-group mask' not in invalid.stderr:
        raise ValueError('invalid CPU was not rejected')
    save(args.output/'inventory.json', inventory)
    groups = {}
    for item in inventory:
        key = json.dumps(item['cache_info'], sort_keys=True)
        groups.setdefault(key, []).append(item)
    if len(groups) != 2:
        save(args.output/'unsupported-topology.json', {'distinct_cache_classes':len(groups), 'model_forward_executed':False})
        raise ValueError('this preregistration requires exactly two observed cache classes')
    selected = sorted((items[0] for items in groups.values()), key=lambda v:tuple(e['cache_bytes'] for e in v['cache_info']))
    configurations = dict(zip(['cacheA','cacheB'], selected)); orders = [['cacheA','cacheB'], ['cacheB','cacheA']]
    schedules = [[{'case':i, 'warmup':False} for i in [0,1,0,1]], [{'case':i, 'warmup':False} for i in [1,0,1,0]]]
    save(args.output/'preregistration.json', {'date_utc':datetime.now(timezone.utc).isoformat(),
        'script_sha256':sha(__file__), 'generator_sha256':sha(ROOT/'runtime/onnx/prepare_native_cache_diagnostic.py'),
        'helper_sha256':sha(ROOT/'runtime/onnx/benchmark_pilot.py'), 'host_helper_sha256':sha(ROOT/'runtime/onnx/diagnose_native_repeats.py'),
        'executable_sha256':sha(exe), 'generation_sha256':sha(generation), 'assets':old_pre['assets'],
        'previous_failure_preregistration_sha256':sha(failure/'preregistration.json'),
        'case_ids':ids, 'configurations':configurations, 'orders':orders, 'schedules':schedules,
        'inventory_sha256':sha(args.output/'inventory.json'), 'process_mask':mask.value, 'threads':4,
        'sessions_per_cache_class':2, 'repeats_per_case_per_session':2, 'planned_forwards':16,
        'timeout_seconds':600, 'memory_limit_bytes':limit, 'host_before':host_state(),
        'scope':'pin only diagnostic main thread during explicit CACHE_INFO initialization; restore full original thread mask before pool/model/forward',
        'numerical_acceptance':'ONNX probability<=1e-4,sum<=1e-6,judgment/tokens exact; input IDs exact; finite hidden1024/raw255; cache class exact and affinity restored',
        'causal_question':'does controlled cache initialization reproduce the old-gate vs failed-session probability offset, and does hidden output already differ?',
        'repeat_threshold_unchanged':1e-6, 'global_28_case_reacceptance':False, 'performance_acceptance':False, 'formal_slo_acceptance':False,
        'limitations':['two cases, two sessions/class, two repeats/session; not all28 or held-out input data',
            'new instrumented exe; feature sets/version/backbone/weights identical, explicit early cache init changes initialization',
            'hypothetical_kernel_params are representative calculations, not actual GEMM-call parameter telemetry',
            'main thread mask restored; worker core placement/temperature/frequency not measured or controlled',
            'raw/hidden JSON f32 decimals normalized to binary f32 before differences; Native probabilities are f64 conversions of f32',
            'timings diagnostic only, no warmup/SLO/backend adoption/recognition quality']})
    rows = []
    for block, order in enumerate(orders):
        for name in order:
            run_id = f'diagnostic-{block}-{name}'; config = configurations[name]
            job = args.output/(run_id+'.job.json')
            save(job, {'threads':4, 'retained_f32':True, 'cache_init_cpu':config['requested_cpu'], 'cases':cases, 'schedule':schedules[block]})
            print('START', run_id, flush=True); before = host_state()
            row = invoke([exe.resolve(), manifest.resolve(), job.resolve()], args.output, run_id, limit); after = host_state()
            events = [json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
            validate_events(events, cases, policy, expected_threads=4); init = events[0]; actual = init['cache_diagnostic']
            if actual != config or len(events) != 6:
                raise ValueError('cache/schedule metadata changed')
            if (init['requested_threads'], init['rayon_pool_threads'], init['candle_env_threads'], init['expected_barrier_aux_workers'], init['manifest_cpu_threads']) != (4,4,'4',3,1):
                raise ValueError('pool configuration mismatch')
            if not init['retained_f32'] or (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes']) != (320,3009572096,1,1044480):
                raise ValueError('cache payload mismatch')
            for e, item in zip(events[1:-1], schedules[block]):
                case = cases[item['case']]; expected_ids = [token for token, active in zip(case['inputs']['input_ids'], case['inputs']['attention_mask']) if active]
                if e['case'] != case['id'] or e['warmup'] or e['input_ids'] != expected_ids or e['physical_tokens'] != case['tokens']:
                    raise ValueError('input/schedule mismatch')
                for key, size in [('hidden_values',1024), ('raw_logits',255)]:
                    if len(e[key]) != size or not all(math.isfinite(x) for x in e[key]):
                        raise ValueError('invalid diagnostic vector')
                if not all(mask.value & (1 << e[key]) for key in ['processor_before','processor_after']):
                    raise ValueError('forward processor outside allowed mask')
                e['old_native4_gate_error'] = delta(e['probabilities'], old[e['case']])
                e['failed_native4_session_error'] = delta(e['probabilities'], failed[e['case']])
            row.update(events=events, configuration=name, block=block, host_before=before, host_after=after)
            save(args.output/(run_id+'.validated.json'), row); rows.append(row); print('DONE', run_id, flush=True)
    summary = {'observed_forwards':16, 'all_numeric_resource_gates_passed':True,
        'max_onnx_error':max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),
        'global_28_case_reacceptance':False, 'performance_acceptance':False, 'formal_slo_acceptance':False, 'cases':{}}
    for case in cases:
        per_class = {name:[e for r in rows if r['configuration']==name for e in r['events'][1:-1] if e['case']==case['id']] for name in configurations}
        entry = {'tokens':case['tokens'], 'classes':{}}
        for name, es in per_class.items():
            if len(es) != 4:
                raise ValueError('repeat coverage mismatch')
            entry['classes'][name] = {'observations':4, 'probabilities_exact':all(e['probabilities']==es[0]['probabilities'] for e in es),
                'hidden_exact':all(e['hidden_values']==es[0]['hidden_values'] for e in es),
                'raw_exact':all(e['raw_logits']==es[0]['raw_logits'] for e in es),
                'max_old_gate_error':max(e['old_native4_gate_error'] for e in es),
                'max_failed_session_error':max(e['failed_native4_session_error'] for e in es)}
        a = per_class['cacheA'][0]; b = per_class['cacheB'][0]
        entry.update(probability_class_delta=delta(a['probabilities'],b['probabilities']),
            hidden_class_delta=delta(f32(a['hidden_values']),f32(b['hidden_values'])),
            raw_class_delta=delta(f32(a['raw_logits']),f32(b['raw_logits'])), input_ids_equal=a['input_ids']==b['input_ids'])
        summary['cases'][case['id']] = entry
    save(args.output/'summary.json', summary); print('COMPLETE', flush=True)


if __name__ == '__main__':
    main()
