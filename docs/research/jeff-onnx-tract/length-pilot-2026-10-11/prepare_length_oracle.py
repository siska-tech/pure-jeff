"""Development-only CPU ONNX reference for the frozen Rust length fixtures."""
import argparse
import ctypes as c
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from benchmark_pilot import ROOT, MemoryStatus, invoke, save, sha


def worker(spec_path):
    import numpy as np
    import onnxruntime as ort
    from check_oracle import probabilities
    sys.path.insert(0, str(ROOT/'runtime'))
    import jeff_worker
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.log_severity_level = 3
    session = ort.InferenceSession(spec['model'], sess_options=options, providers=['CPUExecutionProvider'])
    if session.get_providers() != ['CPUExecutionProvider']:
        raise ValueError('CPU oracle required')
    print(json.dumps({'event': 'initialized', 'provider': session.get_providers(),
        'worker_interpreter': sys.executable, 'python_version': sys.version,
        'onnxruntime_version': ort.__version__, 'numpy_version': np.__version__,
        'threads': 1, 'optimization': 'disabled', 'performance_benchmark': False}), flush=True)
    for case in spec['cases']:
        inputs = {key: np.array([value], dtype=np.int64) for key,value in case['inputs'].items()}
        (raw,) = session.run(['logits'], inputs)
        if raw.shape != (1,255) or raw.dtype != np.float32 or not np.isfinite(raw).all():
            raise ValueError('invalid logits')
        probs = probabilities(raw[0], len(case['request']['candidates']), case['temperature']).tolist()
        judgment = jeff_worker.pack_observation(case['request'], probs, case['temperature'],
            case['tokens'], spec['policy'], [])['judgment']
        record = {'event': 'reference', 'case': case['id'], 'raw_logits': raw[0].tolist(),
            'probabilities': probs, 'judgment': judgment, 'effective_tokens': case['tokens']}
        if 'expected_probabilities' in case:
            error = max(abs(x-y) for x,y in zip(probs,case['expected_probabilities']))
            if error > 1e-4 or judgment != case['expected_judgment']:
                raise ValueError('existing golden oracle gate failed')
            record['golden_probability_error'] = error
        print(json.dumps(record, ensure_ascii=False, allow_nan=False), flush=True)
    print(json.dumps({'event': 'completed', 'cases': len(spec['cases'])}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    if not args.output:
        parser.error('--output required')
    previous = ROOT/'docs/research/jeff-onnx-tract/accepted-threads-2026-10-11'
    fixture = previous/'length-inputs.json'
    index = json.loads((previous/'file-index.json').read_text(encoding='utf-8'))
    if sha(fixture) != next(f['sha256'] for f in index if f['path']==fixture.name):
        raise ValueError('frozen fixture changed')
    data = json.loads(fixture.read_text(encoding='utf-8'))
    model = ROOT/'experiments/runs/onnx-current-step1113-v2/model.normalized.onnx'
    model_hash = '4808e28131967e8ed33f8b50d46c4212e11c19b79e6dfb5209cf9b6931cd9b0c'
    export = json.loads((model.parent/'export.json').read_text(encoding='utf-8'))
    if sha(model) != model_hash or len(data['cases']) != 24:
        raise ValueError('wrong frozen model or fixture count')
    for asset in export['assets']:
        if sha(model.parent/asset['path']) != asset['sha256']:
            raise ValueError('export asset changed')
    manifest = ROOT/'models/jeff-rust-bundle-p3.json'
    if sha(manifest) != data['manifest_sha256']:
        raise ValueError('manifest changed')
    policy = json.loads(manifest.read_text(encoding='utf-8'))['policy']
    goldens = json.loads((previous/'gate-4.job.json').read_text(encoding='utf-8'))['cases']
    for case in goldens:
        if sha(ROOT/'tests/fixtures/jeff-golden'/(case['id']+'.json')) != case['golden_sha256']:
            raise ValueError('golden changed')
    cases = goldens+data['cases']
    memory = MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys < 4*1024**3:
        raise RuntimeError('need 4 GiB available RAM')
    limit = min(8*1024**3,memory.ullTotalPhys//2)
    args.output.mkdir(parents=True,exist_ok=False)
    interpreter = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
    save(args.output/'preregistration.json', {'date_utc':datetime.now(timezone.utc).isoformat(),
        'direct_worker_interpreter':str(interpreter),'worker_interpreter_sha256':sha(interpreter),
        'memory_scope':'direct Python process executing ONNX Runtime; bypass Windows venv launcher',
        'fixture_sha256':sha(fixture),'model_sha256':model_hash,'external_weights_sha256':sha(model.parent/'model.onnx.data'),
        'manifest_sha256':sha(manifest),'script_sha256':sha(__file__),
        'probability_helper_sha256':sha(ROOT/'runtime/onnx/check_oracle.py'),
        'policy_helper_sha256':sha(ROOT/'runtime/jeff_worker.py'),
        'cases':28,'threads':1,'optimization':'disabled','provider':'CPUExecutionProvider',
        'performance_benchmark':False,'timeout_seconds':600,'memory_limit_bytes':limit,
        'available_physical_bytes':memory.ullAvailPhys,'quality_labels':False})
    spec = args.output/'oracle.job.json'
    save(spec, {'model':str(model.resolve()),'policy':policy,'cases':cases})
    record = invoke([interpreter,'-B',Path(__file__).resolve(),'--worker',spec.resolve()],args.output,'oracle',limit)
    events = [json.loads(line) for line in (args.output/'oracle.stdout.jsonl').read_text(encoding='utf-8').splitlines()]
    if len(events) != 30 or events[-1] != {'event':'completed','cases':28}:
        raise ValueError('oracle schedule incomplete')
    if Path(events[0]['worker_interpreter']).resolve() != interpreter or record['peak_working_set_bytes'] < 512*1024**2:
        raise ValueError('oracle worker memory scope not confirmed')
    result = []
    for case,event in zip(cases,events[1:-1]):
        if event['case'] != case['id'] or event['effective_tokens'] != case['tokens']:
            raise ValueError('oracle schedule mismatch')
        result.append({**case,'expected_probabilities':event['probabilities'],
            'expected_judgment':event['judgment'],'reference_raw_logits':event['raw_logits']})
    save(args.output/'oracle.json', {'passed':True,'performance_benchmark':False,
        'model_sha256':model_hash,'fixture_sha256':sha(fixture),'cases':result,
        'initialization':events[0],'process':record})
    print('COMPLETE 4 goldens + 24 length references',flush=True)


if __name__ == '__main__':
    main()
