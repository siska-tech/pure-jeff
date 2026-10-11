"""Preregistered observer on/off pilot; no equivalence or formal SLO claim."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events
from observe_windows_host import WindowsReader, invoke_observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    accepted = ROOT/'docs/research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11'
    observer = ROOT/'docs/research/jeff-onnx-tract/host-observer-2026-10-11'
    for directory in [accepted, observer]:
        for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/item['path']) != item['sha256']:
                raise ValueError('previous evidence changed')
    integration = json.loads((observer/'integration/summary.json').read_text(encoding='utf-8'))
    if not integration['all_numeric_and_sampled_host_conditions_passed'] or integration['forwards'] != 6:
        raise ValueError('observer integration acceptance required')
    pre = json.loads((accepted/'preregistration.json').read_text(encoding='utf-8'))
    for asset in pre['assets']:
        if sha(ROOT/asset['path']) != asset['sha256']:
            raise ValueError('frozen asset changed')
    case = next(r for r in json.loads((accepted/'reference-cases.json').read_text(encoding='utf-8'))
                if r['id'] == 'synthetic-ocr-ascii-3-128')
    native_ref = json.loads((accepted/'old-native-gate-reference.json').read_text(encoding='utf-8'))[case['id']]
    tract_ref = next(json.loads(line)['raw_logits'] for path in sorted(accepted.glob('gate-tract4-*.stdout.jsonl'))
                     for line in path.read_text(encoding='utf-8').splitlines() if json.loads(line).get('case') == case['id'])
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'
    policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    mem = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(mem)) or mem.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, mem.ullTotalPhys//2)
    orders = [['native4-off', 'native4-on', 'tract4-on', 'tract4-off'],
              ['tract4-off', 'tract4-on', 'native4-on', 'native4-off']]
    schedule = [{'case': 0, 'warmup': i < 5} for i in range(8)]
    reader = WindowsReader(); initial = reader()
    if initial['power_status_raw']['ac_line_status'] != 1 or initial['power_status_raw']['system_status_flag'] != 0:
        raise ValueError('AC connected / battery saver off required')
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'preregistration.json', {'utc': datetime.now(timezone.utc).isoformat(),
         'script_sha256': sha(__file__), 'observer_sha256': sha(Path(__file__).with_name('observe_windows_host.py')),
         'helper_sha256': sha(Path(__file__).with_name('benchmark_pilot.py')),
         'host_helper_sha256': sha(Path(__file__).with_name('diagnose_native_repeats.py')),
         'accepted_index_sha256': sha(accepted/'file-index.json'), 'observer_acceptance_index_sha256': sha(observer/'file-index.json'),
         'assets': pre['assets'], 'orders': orders, 'cases': [case], 'schedule': schedule,
         'planned_processes': 8, 'planned_forwards': 64, 'measured_per_backend_mode': 6,
         'cache_configuration': pre['cache_configuration'], 'sample_interval_seconds': 1,
         'memory_limit_bytes': limit, 'timeout_seconds': 600, 'host_initial': initial,
         'numeric_acceptance': 'ONNX1e-4,sum1e-6,judgment/tokens;Native old/all-pairs1e-6;Tract raw exact',
         'host_acceptance': 'AC1,saver0,scheme/mask/topology same as initial at boundaries;on cadence/error gates also required',
         'descriptive_material_change_fraction': .05,
         'quantile': 'nearest rank; n6 p95=max', 'formal_slo_acceptance': False, 'equivalence_acceptance': False,
         'limitations': ['one existing artificial128 input;two sessions/mode/backend;partially balanced order;no holdout',
                        'Native computes128,Tract physical512;only within-backend on/off contrasts',
                        'off mode has boundary snapshots only;temperature/hardware frequency/compute affinity/background uncontrolled',
                        'parent CPU is observer+existing process guard and excludes child CPU;wrapper wall includes observer startup/finish',
                        '5% is preregistered descriptive screen,not confidence bound or equivalence margin acceptance']})
    rows = []; native_history = []
    topology = lambda s: [(r['id'], r['group'], r['logical_processor'], r['core'], r['efficiency_class']) for r in s['cpu_sets']]
    try:
        for block, order in enumerate(orders):
            for config in order:
                name, mode = config.split('-'); native = name == 'native4'; run = f'block{block}-{config}'
                exe = ROOT/('.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe' if native else '.venv/tract-scatter-target/release/bench.exe')
                asset = manifest if native else ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
                job = args.output/(run+'.job.json')
                save(job, {'threads': 4, 'retained_f32': True, 'mode': 'nnef-decluttered', 'profile_codegen': False,
                           'profile_forward': False, 'cache_init_cpu': pre['cache_configuration']['requested_cpu'],
                           'cases': [case], 'schedule': schedule})
                before = reader(); print('START', run, flush=True)
                begin = time.perf_counter_ns(); cpu_begin = time.process_time_ns()
                fn = invoke_observed if mode == 'on' else invoke
                row = fn([exe.resolve(), asset.resolve(), job.resolve()], args.output, run, limit)
                parent_cpu_ns = time.process_time_ns()-cpu_begin; wrapper_wall_ns = time.perf_counter_ns()-begin
                after = reader()
                for s in [before, after]:
                    if (s['power_status_raw']['ac_line_status'] != 1 or s['power_status_raw']['system_status_flag'] != 0
                        or s['active_scheme_guid'] != initial['active_scheme_guid'] or s['observer_affinity'] != initial['observer_affinity']
                        or topology(s) != topology(initial)):
                        raise ValueError('host boundary condition changed')
                events = [json.loads(line) for line in (args.output/(run+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
                validate_events(events, [case], policy, expected_threads=4)
                if len(events) != 10:
                    raise ValueError('event count')
                init = events[0]
                if native:
                    if (init['cache_diagnostic'] != pre['cache_configuration'] or
                        (init['requested_threads'], init['rayon_pool_threads'], init['candle_env_threads'], init['expected_barrier_aux_workers'], init['manifest_cpu_threads']) != (4, 4, '4', 3, 1) or
                        not init['retained_f32'] or (init['cached_tensors'], init['cached_bytes'], init['head_cached_tensors'], init['head_cached_bytes']) != (320, 3009572096, 1, 1044480)):
                        raise ValueError('Native configuration mismatch')
                elif init['executor_threads'] != 4 or not init['multithread_mm']:
                    raise ValueError('Tract configuration mismatch')
                for e, item in zip(events[1:-1], schedule):
                    if e['case'] != case['id'] or e['warmup'] != item['warmup'] or e['physical_tokens'] != (128 if native else 512):
                        raise ValueError('schedule/shape mismatch')
                    if native:
                        if max(abs(a-b) for a, b in zip(e['probabilities'], native_ref)) > 1e-6:
                            raise ValueError('Native reference mismatch')
                        if any(max(abs(a-b) for a, b in zip(e['probabilities'], p)) > 1e-6 for p in native_history):
                            raise ValueError('Native pairwise repeat mismatch')
                        native_history.append(e['probabilities']); e['compute_ns'] = e['backbone_ns']+e['head_softmax_ns']
                    else:
                        if e['raw_logits'] != tract_ref or e['forward_profile']:
                            raise ValueError('Tract raw/profile mismatch')
                        e['compute_ns'] = e['forward_ns']+e['score_ns']
                row.update(events=events, block=block, backend=name, mode=mode, host_before=before, host_after=after,
                           wrapper_wall_ns=wrapper_wall_ns, parent_cpu_ns=parent_cpu_ns)
                save(args.output/(run+'.validated.json'), row); rows.append(row)
                print('DONE', run, flush=True)
        result = {'processes': 8, 'forwards': 64, 'all_numeric_host_resource_gates_passed': True,
                  'max_onnx_probability_error': max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),
                  'native_repeat_exact': all(p == native_history[0] for p in native_history),
                  'formal_slo_acceptance': False, 'equivalence_acceptance': False, 'configurations': {}, 'pairs': []}
        for name in ['native4', 'tract4']:
            result['configurations'][name] = {}
            for mode in ['off', 'on']:
                selected = [r for r in rows if r['backend'] == name and r['mode'] == mode]
                es = [e for r in selected for e in r['events'][1:-1] if not e['warmup']]
                result['configurations'][name][mode] = {**{k: stats([e[k]/1e9 for e in es]) for k in ['compute_ns', 'request_ns']},
                     **{k: stats([r[k]/1e9 for r in selected]) for k in ['wrapper_wall_ns', 'parent_process_ns', 'parent_cpu_ns']},
                     'startup_ns': stats([r['events'][0]['startup_ns']/1e9 for r in selected]),
                     'peak_working_set_bytes': stats([r['peak_working_set_bytes'] for r in selected])}
            for block in range(2):
                pair = {r['mode']: stats([e['compute_ns']/1e9 for e in r['events'][1:-1] if not e['warmup']])
                        for r in rows if r['backend'] == name and r['block'] == block}
                result['pairs'].append({'backend': name, 'block': block, 'compute_seconds': pair,
                     'on_minus_off_median_seconds': pair['on']['median']-pair['off']['median'],
                     'on_over_off_median_minus_one': pair['on']['median']/pair['off']['median']-1})
        save(args.output/'summary.json', result)
        print('COMPLETE', flush=True)
    except Exception as error:
        save(args.output/'failure.json', {'error': repr(error), 'validated_runs': [r['run_id'] for r in rows],
                                        'formal_slo_acceptance': False, 'equivalence_acceptance': False})
        raise


if __name__ == '__main__':
    main()
