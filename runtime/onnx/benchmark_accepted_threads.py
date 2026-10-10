"""Unprofiled four/eight-thread pilot using the frozen accepted Scatter binary."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha, stats, validate_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    previous = ROOT/'docs/research/jeff-onnx-tract/scatter-rows-2026-10-11'
    frozen = json.loads((previous/'preregistration.json').read_text(encoding='utf-8'))
    exe = ROOT/'.venv/tract-scatter-target/release/bench.exe'
    generation = ROOT/'.venv/tract-scatter-candidate/generation.json'
    model = ROOT/'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar'
    for path, expected in [(exe, frozen['candidate_executable_sha256']),
        (generation, frozen['generation_sha256']), (model, frozen['model_sha256'])]:
        if sha(path) != expected:
            raise ValueError('frozen asset changed: '+str(path))
    generated = json.loads(generation.read_text(encoding='utf-8'))
    for item in generated['files']:
        if sha(generation.parent/item['path']) != item['sha256']:
            raise ValueError('generated source changed')
    cases = json.loads((previous/'gate-control.job.json').read_text(encoding='utf-8'))['cases']
    if len(cases) != 4:
        raise ValueError('four goldens required')
    for case in cases:
        path = ROOT/'tests/fixtures/jeff-golden'/(case['id']+'.json')
        golden = json.loads(path.read_text(encoding='utf-8'))
        if sha(path) != case['golden_sha256'] or golden['request'] != case['request']:
            raise ValueError('golden changed')
        for key, values in golden['official']['inputs'].items():
            if case['inputs'][key] != [248044 if key == 'input_ids' else 0]*(512-len(values[0]))+values[0]:
                raise ValueError('prepared inputs changed')
    refs = {e['case']: e['raw_logits'] for e in [json.loads(line) for line in
        (previous/'gate-control.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3, memory.ullTotalPhys//2)
    policy = json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
    orders = [[4,8], [8,4], [4,8]]
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output/'preregistration.json', {'date_utc': datetime.now(timezone.utc).isoformat(),
        'executable_sha256': sha(exe), 'generation_sha256': sha(generation), 'model_sha256': sha(model),
        'script_sha256': sha(__file__), 'source_job_sha256': sha(previous/'gate-control.job.json'),
        'reference_raw_sha256': sha(previous/'gate-control.stdout.jsonl'),
        'orders': orders, 'sessions_per_thread': 3, 'warmups_per_session': 1, 'samples_per_session': 3,
        'profile_enabled': False, 'formal_slo_acceptance': False,
        'selection_rule': 'prefer 8 only if all three paired session medians and pooled median/p95 improve; otherwise retain 4',
        'timeout_seconds': 600, 'memory_limit_bytes': limit, 'available_physical_bytes': memory.ullAvailPhys,
        'scope': 'candidate-request effective128 physical512, prepared tensors, same accepted binary',
        'limitations': ['n=9 nearest-rank p95 is max, no confidence interval',
            'thermals, affinity, background load and storage cache uncontrolled',
            'startup and lifetime peaks n=3 are incidental, not cold campaign',
            'no tokenizer/API E2E, Native comparison or quality acceptance']})
    records = []
    def run(run_id, threads, schedule):
        job = args.output/(run_id+'.job.json')
        save(job, {'mode': 'nnef-decluttered', 'profile_codegen': False, 'profile_forward': False,
            'threads': threads, 'cases': cases, 'schedule': schedule})
        print('START', run_id, flush=True)
        record = invoke([exe.resolve(), model.resolve(), job.resolve()], args.output, run_id, limit)
        events = [json.loads(line) for line in (args.output/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        validate_events(events, cases, policy, expected_threads=threads)
        if len(events) != len(schedule)+2 or events[0]['executor_threads'] != threads or not events[0]['multithread_mm']:
            raise ValueError('executor/schedule mismatch')
        for event, item in zip(events[1:-1], schedule):
            raw = event['raw_logits']
            if (event['case'] != cases[item['case']]['id'] or event['warmup'] != item['warmup']
                or event['forward_profile'] or len(raw) != 255 or not all(math.isfinite(v) for v in raw)
                or raw != refs[event['case']]):
                raise ValueError('schedule/profile/numeric mismatch')
        record.update(threads=threads, events=events)
        save(args.output/(run_id+'.validated.json'), record)
        records.append(record)
        print('DONE', run_id, [round(e['forward_ns']/1e9,3) for e in events[1:-1]], flush=True)
    for threads in [4,8]:
        run(f'gate-{threads}', threads, [{'case': i, 'warmup': False} for i in range(4)])
    schedule = [{'case': 0, 'warmup': True}]+[{'case': 0, 'warmup': False}]*3
    for block, order in enumerate(orders):
        for threads in order:
            run(f'resident-{block}-{threads}', threads, schedule)
    summary = {'formal_slo_acceptance': False, 'raw_logits_exact': True, 'processes': len(records),
        'forwards': sum(len(r['events'])-2 for r in records), 'threads': {},
        'max_probability_error': max(e['probability_max_abs_error'] for r in records for e in r['events'][1:-1])}
    for threads in [4,8]:
        rows = [r for r in records if r['threads'] == threads and r['run_id'].startswith('resident-')]
        summary['threads'][str(threads)] = {
            'warm_forward_seconds': stats([e['forward_ns']/1e9 for r in rows for e in r['events'][1:-1] if not e['warmup']]),
            'session_medians_seconds': [stats([e['forward_ns']/1e9 for e in r['events'][1:-1] if not e['warmup']])['median'] for r in rows],
            'startup_seconds': stats([r['events'][0]['startup_ns']/1e9 for r in rows]),
            'peak_working_set_bytes': stats([r['peak_working_set_bytes'] for r in rows])}
    a,b = [summary['threads'][str(t)] for t in [4,8]]
    deltas = [y-x for x,y in zip(a['session_medians_seconds'], b['session_medians_seconds'])]
    prefer8 = all(d < 0 for d in deltas) and all(b['warm_forward_seconds'][q] < a['warm_forward_seconds'][q] for q in ['median','p95'])
    summary.update(paired_8_minus_4_seconds=deltas, selected_pilot_threads=8 if prefer8 else 4)
    save(args.output/'summary.json', summary)
    print('COMPLETE', flush=True)


if __name__ == '__main__':
    main()
