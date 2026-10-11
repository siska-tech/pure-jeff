"""Numerical-gated Native4/Tract4 length comparison using the numerically accepted cache-fixed Native exe."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from diagnose_native_repeats import host_state
from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    accepted = ROOT/'docs/research/jeff-onnx-tract/native-cache-timing-gate-2026-10-11'
    for item in json.loads((accepted/'file-index.json').read_text(encoding='utf-8')):
        if sha(accepted/item['path']) != item['sha256']:
            raise ValueError('cache-fixed numeric evidence changed')
    numeric = json.loads((accepted/'summary.json').read_text(encoding='utf-8'))
    if not numeric['all_numeric_resource_gates_passed'] or numeric['forwards'] != 84:
        raise ValueError('full28 timing-wrapper numeric acceptance required')
    native_pre = json.loads((accepted/'preregistration.json').read_text(encoding='utf-8'))
    cache_configuration = native_pre['configuration']
    previous_gate = json.loads((accepted/'old-gate-reference.json').read_text(encoding='utf-8'))
    prior = ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'
    length = ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
    for directory in [prior, length]:
        for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/item['path']) != item['sha256']:
                raise ValueError('previous evidence changed')
    old = json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    tract_pre = json.loads((length/'preregistration.json').read_text(encoding='utf-8'))
    oracle = json.loads((length/'oracle-oracle.json').read_text(encoding='utf-8'))
    if not oracle['passed']:
        raise ValueError('successful oracle required')
    cases = oracle['cases']
    refs = json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'))
    tract_refs = {e['case']: e['raw_logits'] for e in [json.loads(line) for line in
        (length/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    native = ROOT/'.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe'
    tract = ROOT/'.venv/tract-scatter-target/release/bench.exe'
    model = ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'
    ng = ROOT/'.venv/native-cache-fixed-candidate/generation.json'
    tg = ROOT/'.venv/tract-scatter-candidate/generation.json'
    assets = [(native, native_pre['executable_sha256']), (tract, tract_pre['executable_sha256']),
        (model, tract_pre['model_sha256']), (ng, native_pre['generation_sha256']), (tg, tract_pre['generation_sha256'])]
    assets.extend((ROOT/a['path'], a['sha256']) for a in old['assets'])
    for generation in [ng, tg]:
        assets.extend((generation.parent/a['path'], a['sha256']) for a in
            json.loads(generation.read_text(encoding='utf-8'))['files'])
    for p, h in assets:
        if sha(p) != h:
            raise ValueError(f'frozen asset changed: {p}')
    for item in json.loads((prior/'prior-thread-audit.json').read_text(encoding='utf-8'))['sources'].values():
        if sha(item['path']) != item['sha256']:
            raise ValueError('audited source changed')
    policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    for case in cases:
        count = len(case['request']['candidates'])
        if not 2 <= count <= 255 or case.get('candidate_count', count) != count:
            raise ValueError('candidate count mismatch')
        case['count'] = count
    primary = [i for i, case in enumerate(cases) if 'variant' in case and case['candidate_count'] != 8]
    lengths = [128, 256, 384, 511, 512]
    if len(cases) != 28 or len(primary) != 20 or policy['cpu_threads'] != 1:
        raise ValueError('fixed cases/policy required')
    if any(sum(cases[i]['tokens'] == n for i in primary) != 4 for n in lengths):
        raise ValueError('length coverage mismatch')
    for i in primary:
        case = cases[i]; n = case['tokens']
        if case['inputs']['attention_mask'] != [0]*(512-n)+[1]*n or case['inputs']['mm_token_type_ids'] != [0]*512:
            raise ValueError('left-padded text only')
    configurations = {'native4': 4, 'tract4': 4}
    orders = [['native4', 'tract4'], ['tract4', 'native4'], ['native4', 'tract4']]
    variants = sorted({cases[i]['variant'] for i in primary})
    schedules = []
    for block in range(3):
        warm = [next(i for i in primary if cases[i]['tokens'] == n and cases[i]['variant'] == variants[block]) for n in lengths]
        measured = primary.copy(); random.Random(7901113+block).shuffle(measured)
        schedules.append([{'case': i, 'warmup': True} for i in warm]+[{'case': i, 'warmup': False} for i in measured])
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, memory.ullTotalPhys//2)
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'preregistration.json', {'date_utc': datetime.now(timezone.utc).isoformat(),
        'script_sha256': sha(__file__), 'helper_sha256': sha(ROOT/'runtime/onnx/benchmark_pilot.py'),
        'previous_native_preregistration_sha256': sha(prior/'preregistration.json'),
        'cache_fixed_acceptance_index_sha256': sha(accepted/'file-index.json'),
        'cache_configuration': cache_configuration, 'host_before': host_state(),
        'host_helper_sha256': sha(ROOT/'runtime/onnx/diagnose_native_repeats.py'),
        'oracle_sha256': sha(length/'oracle-oracle.json'), 'native_probabilities_sha256': sha(prior/'previous-native-probabilities.json'),
        'tract_raw_sha256': sha(length/'gate.stdout.jsonl'), 'prior_audit_sha256': sha(prior/'prior-thread-audit.json'),
        'assets': [{'path': p.relative_to(ROOT).as_posix(), 'sha256': h} for p, h in assets],
        'configurations': configurations, 'orders': orders, 'schedules': schedules, 'seed': 7901113,
        'gate_chunks_per_configuration': 4, 'planned_processes': 14, 'planned_forwards': 206,
        'sessions_per_configuration': 3, 'samples_per_length_per_configuration': 12,
        'warmups_per_session': 5, 'samples_per_session': 20, 'gate_cases_per_configuration': 28,
        'lengths': lengths, 'primary_indices': primary, 'timeout_seconds': 600,
        'memory_limit_bytes': limit, 'available_physical_bytes': memory.ullAvailPhys,
        'formal_slo_acceptance': False, 'held_out_input_data': False,
        'numerical_acceptance': 'ONNX probability maxabs<=1e-4,sum<=1e-6,judgment/tokens exact; existing Native references maxabs<=1e-4 where available; Native old gate and pairwise per-case repeat<=1e-6; AC connected/battery saver off before and after each child; Tract raw exactly previous four-thread length gate',
        'performance_acceptance': 'descriptive length pilot only; no backend adoption, runtime-only effect or SLO acceptance',
        'scope': 'step1113 FP32 batch1 four threads; Native effective length, Tract physical512; same old artificial fixtures, independent sessions/seed',
        'limitations': ['n=12/length p95=max; n=3/input and 3 independent resident sessions/configuration',
            'AB/BA/AB partially balanced; Native cache init fixed/restored, compute affinity/thermals/background/storage cache uncontrolled; power/system CPU snapshots only',
            'length/content confounded; primary candidate counts2/3; eight-candidate extras gate-only, no128 cell',
            'five mixed-length warmups, one per length; not five per cell or formal SLO campaign',
            'Native text320/head1 FP32 vs Tract FP32 packed plan; algorithms/layout/kernel boundaries differ',
            'Native tokenizer/policy vs Tract prepared tensors; startup verification/request scopes unequal, no API E2E',
            'lifetime peaks n=3 incidental include startup/mapped/shared pages; not warm private memory/cold campaign',
            'pool settings checked, no active-worker telemetry or OS thread cap; no real OCR/ASR labels']})
    rows = []; gate_refs = {}; history = {}
    save(args.output/'reference-cases.json', cases)
    def run(configuration, run_id, schedule, gate=False):
        is_native = configuration == 'native4'
        job = args.output/(run_id+'.job.json')
        save(job, {'threads': 4, 'retained_f32': True, 'mode': 'nnef-decluttered',
            'profile_codegen': False, 'profile_forward': False, 'cache_init_cpu': cache_configuration['requested_cpu'], 'cases': cases, 'schedule': schedule})
        print('START', run_id, flush=True)
        exe, asset = (native, manifest) if is_native else (tract, model)
        before = host_state()
        if before['power_status_raw']['ac_line_status'] != 1 or before['power_status_raw']['system_status_flag'] != 0:
            raise ValueError('AC connected and battery saver off required')
        row = invoke([exe.resolve(), asset.resolve(), job.resolve()], args.output, run_id, limit)
        after = host_state()
        if after['power_status_raw']['ac_line_status'] != 1 or after['power_status_raw']['system_status_flag'] != 0:
            raise ValueError('power condition changed')
        events = [json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events, cases, policy, expected_threads=4); init = events[0]
        if len(events) != len(schedule)+2:
            raise ValueError('event count mismatch')
        if is_native:
            if init['cache_diagnostic'] != cache_configuration:
                raise ValueError('fixed cache/affinity metadata mismatch')
            if (init['requested_threads'] != 4 or init['rayon_pool_threads'] != 4 or init['candle_env_threads'] != '4'
                    or init['expected_barrier_aux_workers'] != 3 or init['manifest_cpu_threads'] != 1 or not init['retained_f32']
                    or (init['cached_tensors'], init['cached_bytes']) != (320, 3009572096)
                    or (init['head_cached_tensors'], init['head_cached_bytes']) != (1, 1044480)):
                raise ValueError('Native configuration/cache mismatch')
        elif init['executor_threads'] != 4 or not init['multithread_mm']:
            raise ValueError('Tract executor mismatch')
        for event, item in zip(events[1:-1], schedule):
            case = cases[item['case']]
            if event['case'] != case['id'] or event['warmup'] != item['warmup'] or event['physical_tokens'] != (case['tokens'] if is_native else 512):
                raise ValueError('shape/schedule mismatch')
            if is_native:
                delta = max(abs(a-b) for a, b in zip(event['probabilities'], refs[event['case']])) if event['case'] in refs else None
                if delta is not None and delta > 1e-4:
                    raise ValueError('frozen Native mismatch')
                old_gate_error = max(abs(a-b) for a,b in zip(event['probabilities'], previous_gate[event['case']]))
                if old_gate_error > 1e-6:
                    raise ValueError('old Native gate mismatch')
                event['old_gate_probability_error'] = old_gate_error
                if gate:
                    gate_refs[event['case']] = event['probabilities']
                repeat = max(abs(a-b) for a, b in zip(event['probabilities'], gate_refs[event['case']]))
                if repeat > 1e-6:
                    raise ValueError('Native repeat mismatch')
                seen = history.setdefault(event['case'], [])
                if any(max(abs(a-b) for a,b in zip(event['probabilities'], p)) > 1e-6 for p in seen):
                    raise ValueError('pairwise Native repeat mismatch')
                seen.append(event['probabilities'])
                event.update(native_probability_max_abs_error=delta, repeat_probability_max_abs_error=repeat,
                    compute_ns=event['backbone_ns']+event['head_softmax_ns'])
            else:
                if event['forward_profile'] or event['raw_logits'] != tract_refs[event['case']]:
                    raise ValueError('Tract raw/profile mismatch')
                event['compute_ns'] = event['forward_ns']+event['score_ns']
        row.update(configuration=configuration, events=events, host_before=before, host_after=after)
        save(args.output/(run_id+'.validated.json'), row); rows.append(row)
        print('DONE', run_id, 'forwards', len(schedule), flush=True)
    gate = [{'case': i, 'warmup': False} for i in range(28)]
    for configuration in configurations:
        for chunk in range(4):
            run(configuration, f'gate-{configuration}-{chunk}', gate[7*chunk:7*chunk+7], True)
    for block, order in enumerate(orders):
        for configuration in order:
            run(configuration, f'resident-{block}-{configuration}', schedules[block])
    es = [e for r in rows for e in r['events'][1:-1]]
    nes = [e for r in rows if r['configuration'] == 'native4' for e in r['events'][1:-1]]
    summary = {'processes': len(rows), 'forwards': len(es), 'numerical_passed': True, 'formal_slo_acceptance': False,
        'max_onnx_probability_error': max(e['probability_max_abs_error'] for e in es),
        'max_native_probability_error': max(e['native_probability_max_abs_error'] for e in nes if e['native_probability_max_abs_error'] is not None),
        'max_native_repeat_error': max(e['repeat_probability_max_abs_error'] for e in nes), 'configurations': {}, 'blocks': []}
    for configuration in configurations:
        resident = [r for r in rows if r['configuration'] == configuration and r['run_id'].startswith('resident')]
        measured = [e for r in resident for e in r['events'][1:-1] if not e['warmup']]
        keys = ['compute_ns', 'request_ns']+(['backbone_ns', 'head_softmax_ns', 'tokenize_ns', 'policy_ns'] if configuration == 'native4' else ['forward_ns', 'score_ns', 'prepare_ns'])
        summary['configurations'][configuration] = {
            'lengths': {str(n): {k: stats([e[k]/1e9 for e in measured if e['effective_tokens'] == n]) for k in keys} for n in lengths},
            'startup_stages_seconds': {k: stats([r['events'][0][k]/1e9 for r in resident]) for k in resident[0]['events'][0] if k.endswith('_ns')},
            'peak_working_set_bytes': stats([r['peak_working_set_bytes'] for r in resident]),
            'inputs': {cases[i]['id']: stats([e['compute_ns']/1e9 for e in measured if e['case'] == cases[i]['id']]) for i in primary}}
    for block in range(3):
        pair = {name: {str(n): stats([e['compute_ns']/1e9 for r in rows if r['run_id'] == f'resident-{block}-{name}'
            for e in r['events'][1:-1] if not e['warmup'] and e['effective_tokens'] == n]) for n in lengths} for name in configurations}
        summary['blocks'].append({'block': block, 'compute_seconds': pair,
            'tract4_minus_native4_median_seconds': {str(n): pair['tract4'][str(n)]['median']-pair['native4'][str(n)]['median'] for n in lengths}})
    save(args.output/'summary.json', summary); print('COMPLETE', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
        args = parser.parse_args()
        if args.output.exists():
            save(args.output/'failure.json', {'error_type':type(error).__name__, 'error':str(error),
                'validated_runs':sorted(p.name for p in args.output.glob('*.validated.json')),
                'numeric_acceptance':False, 'performance_acceptance':False, 'host_after':host_state()})
        raise
