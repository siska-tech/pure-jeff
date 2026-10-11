"""Six-forward observer integration gate, not a latency benchmark."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, save, sha, validate_events
from observe_windows_host import invoke_observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    accepted = ROOT/'docs/research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11'
    for item in json.loads((accepted/'file-index.json').read_text(encoding='utf-8')):
        if sha(accepted/item['path']) != item['sha256']:
            raise ValueError('accepted archive changed')
    pre = json.loads((accepted/'preregistration.json').read_text(encoding='utf-8'))
    for asset in pre['assets']:
        if sha(ROOT/asset['path']) != asset['sha256']:
            raise ValueError('frozen asset changed')
    case = next(r for r in json.loads((accepted/'reference-cases.json').read_text(encoding='utf-8'))
                if r['id'] == 'synthetic-asr-unicode-2-512')
    native_ref = json.loads((accepted/'old-native-gate-reference.json').read_text(encoding='utf-8'))[case['id']]
    tract_ref = next(json.loads(line)['raw_logits'] for path in sorted(accepted.glob('gate-tract4-*.stdout.jsonl'))
                     for line in path.read_text(encoding='utf-8').splitlines() if json.loads(line).get('case') == case['id'])
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'
    policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    mem = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(mem)) or mem.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, mem.ullTotalPhys//2)
    args.output.mkdir(parents=True, exist_ok=False)
    schedule = [{'case': 0, 'warmup': False}]*3
    save(args.output/'preregistration.json', {'utc': datetime.now(timezone.utc).isoformat(),
         'script_sha256': sha(__file__), 'observer_sha256': sha(Path(__file__).with_name('observe_windows_host.py')),
         'helper_sha256': sha(Path(__file__).with_name('benchmark_pilot.py')),
         'host_helper_sha256': sha(Path(__file__).with_name('diagnose_native_repeats.py')),
         'accepted_index_sha256': sha(accepted/'file-index.json'), 'assets': pre['assets'],
         'order': ['native4', 'tract4'], 'cases': [case], 'schedule': schedule, 'planned_forwards': 6,
         'cache_configuration': pre['cache_configuration'], 'sample_interval_seconds': 1,
         'memory_limit_bytes': limit, 'timeout_seconds': 600,
         'acceptance': 'existing ONNX1e-4,sum1e-6,judgment/tokens;Native old reference and all pairs1e-6;Tract raw exact;sampled host conditions pass',
         'performance_acceptance': False, 'formal_slo_acceptance': False,
         'limitations': ['one old artificial512 case,one session/backend,three repeats,no warmup',
                        'observer overhead uncalibrated;temperature/hardware clock/compute placement/background uncontrolled']})
    rows = []
    try:
        for name in ['native4', 'tract4']:
            native = name == 'native4'
            exe = ROOT/('.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe' if native else '.venv/tract-scatter-target/release/bench.exe')
            asset = manifest if native else ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
            job = args.output/(name+'.job.json')
            save(job, {'threads': 4, 'retained_f32': True, 'mode': 'nnef-decluttered', 'profile_codegen': False,
                       'profile_forward': False, 'cache_init_cpu': pre['cache_configuration']['requested_cpu'],
                       'cases': [case], 'schedule': schedule})
            print('START', name, flush=True)
            row = invoke_observed([exe.resolve(), asset.resolve(), job.resolve()], args.output, name, limit)
            events = [json.loads(line) for line in (args.output/(name+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
            validate_events(events, [case], policy, expected_threads=4)
            if len(events) != 5:
                raise ValueError('event count')
            init = events[0]
            if native:
                if (init['cache_diagnostic'] != pre['cache_configuration'] or
                    (init['requested_threads'], init['rayon_pool_threads'], init['candle_env_threads'], init['expected_barrier_aux_workers'], init['manifest_cpu_threads']) != (4, 4, '4', 3, 1) or
                    not init['retained_f32'] or (init['cached_tensors'], init['cached_bytes'], init['head_cached_tensors'], init['head_cached_bytes']) != (320, 3009572096, 1, 1044480)):
                    raise ValueError('Native configuration mismatch')
            elif init['executor_threads'] != 4 or not init['multithread_mm']:
                raise ValueError('Tract configuration mismatch')
            for e in events[1:-1]:
                if e['case'] != case['id'] or e['warmup'] or e['physical_tokens'] != 512:
                    raise ValueError('schedule/shape mismatch')
                if native:
                    if max(abs(a-b) for a, b in zip(e['probabilities'], native_ref)) > 1e-6:
                        raise ValueError('Native reference mismatch')
                    if any(max(abs(a-b) for a, b in zip(e['probabilities'], other['probabilities'])) > 1e-6 for other in events[1:-1]):
                        raise ValueError('Native pairwise repeat mismatch')
                elif e['raw_logits'] != tract_ref or e['forward_profile']:
                    raise ValueError('Tract raw/profile mismatch')
            row['events'] = events
            save(args.output/(name+'.validated.json'), row); rows.append(row)
            print('DONE', name, flush=True)
        save(args.output/'summary.json', {'forwards': 6, 'all_numeric_and_sampled_host_conditions_passed': True,
             'max_onnx_probability_error': max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]),
             'native_repeat_exact': len({tuple(e['probabilities']) for e in rows[0]['events'][1:-1]}) == 1,
             'performance_acceptance': False, 'formal_slo_acceptance': False})
    except Exception as error:
        save(args.output/'failure.json', {'error': repr(error), 'validated_backends': len(rows), 'performance_acceptance': False})
        raise


if __name__ == '__main__':
    main()
