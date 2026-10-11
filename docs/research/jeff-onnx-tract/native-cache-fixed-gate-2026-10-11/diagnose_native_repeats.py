"""Fixed-size numerical diagnosis after a failed repeat gate; not a benchmark."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, validate_events


class Power(c.Structure):
    _fields_ = [('ac_line_status', c.c_ubyte), ('battery_flag', c.c_ubyte),
        ('battery_life_percent', c.c_ubyte), ('system_status_flag', c.c_ubyte),
        ('battery_life_seconds', c.c_uint32), ('battery_full_life_seconds', c.c_uint32)]


def host_state():
    kernel = c.WinDLL('kernel32', use_last_error=True)
    power = Power(); idle = c.c_uint64(); system = c.c_uint64(); user = c.c_uint64()
    if not kernel.GetSystemPowerStatus(c.byref(power)) or not kernel.GetSystemTimes(c.byref(idle), c.byref(system), c.byref(user)):
        raise OSError(c.get_last_error())
    return {'utc': datetime.now(timezone.utc).isoformat(), 'power_status_raw': {name: getattr(power, name) for name, _ in Power._fields_},
        'system_cpu_100ns': {'idle': idle.value, 'kernel_including_idle': system.value, 'user': user.value}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    failure = ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
    for item in json.loads((failure/'file-index.json').read_text(encoding='utf-8')):
        if sha(failure/item['path']) != item['sha256']:
            raise ValueError('failed-run evidence changed')
    pre = json.loads((failure/'preregistration.json').read_text(encoding='utf-8'))
    for asset in pre['assets']:
        if sha(ROOT/asset['path']) != asset['sha256']:
            raise ValueError('frozen asset changed')
    violations = json.loads((failure/'repeat-violations.json').read_text(encoding='utf-8'))
    ids = sorted({v['case'] for v in violations})
    if len(ids) != 4:
        raise ValueError('four fixed failed cases required')
    ids.append('synthetic-asr-unicode-2-512')
    all_cases = json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
    cases = [next(case for case in all_cases if case['id'] == name) for name in ids]
    old = json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'; policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    exe = ROOT/'.venv/native-threads-target/release/native_retained_bench.exe'
    orders = [[1, 4], [4, 1]]; schedules = []
    for block in range(2):
        schedule = []
        for repeat in range(3):
            indices = list(range(5)); random.Random(4671113+10*block+repeat).shuffle(indices)
            schedule.extend({'case': i, 'warmup': False} for i in indices)
        schedules.append(schedule)
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, memory.ullTotalPhys//2); args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'preregistration.json', {'date_utc': datetime.now(timezone.utc).isoformat(),
        'script_sha256': sha(__file__), 'helper_sha256': sha(ROOT/'runtime/onnx/benchmark_pilot.py'),
        'failure_preregistration_sha256': sha(failure/'preregistration.json'),
        'failure_reference_cases_sha256': sha(failure/'reference-cases.json'),
        'failure_violations_sha256': sha(failure/'repeat-violations.json'),
        'old_gate_sha256': sha(failure/'native-length-gate-probabilities.json'), 'assets': pre['assets'],
        'case_ids': ids, 'orders': orders, 'schedules': schedules, 'seed': 4671113,
        'sessions_per_thread_setting': 2, 'repeats_per_case_per_session': 3, 'planned_forwards': 60,
        'timeout_seconds': 600, 'memory_limit_bytes': limit, 'host_before': host_state(),
        'purpose': 'same-process and cross-process numerical diagnosis of four failed cases plus one512 control; no timing acceptance',
        'stop_condition': 'abort on ONNX maxabs>1e-4,sum>1e-6,judgment/tokens/resource failure; collect fixed60 regardless of repeat1e-6 exceedances',
        'repeat_threshold': 1e-6, 'repeat_threshold_unchanged': True, 'formal_slo_acceptance': False,
        'performance_acceptance': False, 'global_28_case_reacceptance': False,
        'limitations': ['two sessions/setting, three repeats/case/session, same old artificial inputs',
            'no backbone/hidden/raw-logit instrumentation or causal attribution; fixed original exe',
            'power/system-wide CPU snapshots before/after only, no core affinity/frequency/temperature or worker activity telemetry',
            'AC unknown=255; system_status_flag1=battery saver; raw battery life unknown=4294967295',
            'system CPU includes unrelated processes; average utilization is not child CPU or evidence of contention',
            'diagnostic timings not warmed or accepted benchmark results; no SLO/backend adoption']})
    rows = []
    for block, order in enumerate(orders):
        for threads in order:
            run_id = f'diagnostic-{block}-threads{threads}'; job = args.output/(run_id+'.job.json')
            save(job, {'threads': threads, 'retained_f32': True, 'cases': cases, 'schedule': schedules[block]})
            before = host_state(); print('START', run_id, flush=True)
            row = invoke([exe.resolve(), manifest.resolve(), job.resolve()], args.output, run_id, limit)
            after = host_state()
            events = [json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
            validate_events(events, cases, policy, expected_threads=threads); init = events[0]
            if len(events) != 17 or init['requested_threads'] != threads or init['rayon_pool_threads'] != threads or init['candle_env_threads'] != str(threads):
                raise ValueError('pool/schedule mismatch')
            if (not init['retained_f32'] or init['manifest_cpu_threads'] != 1 or init['expected_barrier_aux_workers'] != threads-1
                    or (init['cached_tensors'], init['cached_bytes'], init['head_cached_tensors'], init['head_cached_bytes']) != (320, 3009572096, 1, 1044480)):
                raise ValueError('cache/policy mismatch')
            for event, item in zip(events[1:-1], schedules[block]):
                if event['case'] != cases[item['case']]['id'] or event['warmup'] or event['physical_tokens'] != event['effective_tokens']:
                    raise ValueError('case/shape mismatch')
                event['old_native4_gate_error'] = max(abs(a-b) for a, b in zip(event['probabilities'], old[event['case']]))
            a = before['system_cpu_100ns']; b = after['system_cpu_100ns']
            total = b['kernel_including_idle']+b['user']-a['kernel_including_idle']-a['user']
            if total <= 0:
                raise ValueError('invalid system CPU delta')
            row.update(events=events, threads=threads, block=block, host_before=before, host_after=after,
                system_wide_average_busy_percent=100*(total-(b['idle']-a['idle']))/total)
            save(args.output/(run_id+'.validated.json'), row); rows.append(row)
            print('DONE', run_id, flush=True)
    result = {'observed_forwards': 60, 'all_onnx_probability_judgment_token_gates_passed': True,
        'max_onnx_error': max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),
        'global_28_case_reacceptance': False, 'performance_acceptance': False, 'formal_slo_acceptance': False, 'threads': {}}
    for threads in [1, 4]:
        selected = [r for r in rows if r['threads'] == threads]; per_case = {}
        for case in cases:
            groups = [[e['probabilities'] for e in row['events'][1:-1] if e['case'] == case['id']] for row in selected]
            if any(len(group) != 3 for group in groups):
                raise ValueError('repeat coverage mismatch')
            def span(values):
                return max(max(column)-min(column) for column in zip(*values))
            probabilities = groups[0]+groups[1]
            per_case[case['id']] = {'tokens': case['tokens'], 'within_process_max_span': max(span(group) for group in groups),
                'between_process_first_error': max(abs(a-b) for a, b in zip(groups[0][0], groups[1][0])),
                'all_six_max_span': span(probabilities), 'all_six_exact': all(p == probabilities[0] for p in probabilities),
                'max_old_native4_gate_error': max(abs(a-b) for p in probabilities for a, b in zip(p, old[case['id']]))}
        result['threads'][str(threads)] = {'cases': per_case,
            'subset_span_within_1e6': all(v['all_six_max_span'] <= 1e-6 for v in per_case.values()),
            'subset_old_gate_within_1e6': all(v['max_old_native4_gate_error'] <= 1e-6 for v in per_case.values())}
    save(args.output/'summary.json', result); print('COMPLETE', flush=True)


if __name__ == '__main__':
    main()
