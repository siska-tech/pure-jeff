"""Numerical acceptance of cache-fixed timing exe, with resident repeats; no timing claims."""
import argparse
import ctypes as c
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import subprocess
from benchmark_pilot import ROOT,MemoryStatus,invoke,save,sha,validate_events
from diagnose_native_cache import delta
from diagnose_native_repeats import host_state


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    prior=ROOT/'docs/research/jeff-onnx-tract/native-cache-fixed-gate-2026-10-11'
    diagnostic=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
    for directory in [prior,diagnostic]:
        for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):
            if sha(directory/a['path'])!=a['sha256']:raise ValueError('previous archive changed')
    pre=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
    for a in pre['assets']:
        if sha(ROOT/a['path'])!=a['sha256']:raise ValueError('frozen asset changed')
    gen=ROOT/'.venv/native-cache-fixed-candidate/generation.json'
    for a in json.loads(gen.read_text(encoding='utf-8'))['files']:
        if sha(gen.parent/a['path'])!=a['sha256']:raise ValueError('new source changed')
    audit_path=ROOT/'.venv/native-cache-fixed-source-audit.json'
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    if audit['dependency_packages_features_identical']!=156 or audit['generation_sha256']!=sha(gen) or not audit['cache_module_identical_to_diagnostic']:
        raise ValueError('source/features preflight required')
    cases=json.loads((prior/'reference-cases.json').read_text(encoding='utf-8'))
    old=json.loads((prior/'old-gate-reference.json').read_text(encoding='utf-8'))
    refs=json.loads((prior/'frozen-native-reference.json').read_text(encoding='utf-8'))
    diag={e['case']:e['probabilities'] for p in sorted(prior.glob('gate-0-*.stdout.jsonl'))
        for e in [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()][1:-1]}
    if len(cases)!=28 or set(diag)!=set(old) or any(diag[k]!=old[k] for k in old):raise ValueError('accepted full28 diagnostic references required')
    manifest=ROOT/'models/jeff-rust-bundle-p3.json';policy=json.loads(manifest.read_text(encoding='utf-8'))['policy']
    exe=ROOT/'.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe';config=pre['configuration']
    runs=[]
    for phase,order in [('gate',[0,1,2,3]),('resident',[3,2,1,0])]:
        for chunk in order:
            schedule=[]
            for repeat in range(1 if phase=='gate' else 2):
                indices=list(range(7*chunk,7*chunk+7));random.Random(6791113+(100 if phase=='resident' else 0)+10*chunk+repeat).shuffle(indices)
                schedule.extend({'case':i,'warmup':False} for i in indices)
            runs.append({'id':f'{phase}-chunk{chunk}','phase':phase,'chunk':chunk,'schedule':schedule})
    memory=MemoryStatus(dwLength=c.sizeof(MemoryStatus))
    if not c.WinDLL('kernel32').GlobalMemoryStatusEx(c.byref(memory)) or memory.ullAvailPhys<4*1024**3:raise RuntimeError('need4 GiB available RAM')
    limit=min(8*1024**3,memory.ullTotalPhys//2);args.output.mkdir(parents=True,exist_ok=False)
    invoke([exe.resolve(),'--cache-probe',str(config['requested_cpu'])],args.output,'cache-probe',limit,timeout=30)
    if json.loads((args.output/'cache-probe.stdout.jsonl').read_text(encoding='utf-8'))!=config:raise ValueError('cache probe differs')
    invalid=subprocess.run([str(exe.resolve()),'--cache-probe','64'],capture_output=True,timeout=30)
    save(args.output/'invalid-probe.json',{'cpu':64,'exit_code':invalid.returncode,'stdout':invalid.stdout.decode('utf-8'),'stderr':invalid.stderr.decode('utf-8')})
    if invalid.returncode==0 or invalid.stdout or b'CPU index exceeds single-group mask' not in invalid.stderr:raise ValueError('invalid CPU accepted')
    checks=[ROOT/'.venv'/f'native-cache-fixed-{name}.log' for name in ['build','test','clippy','fmt']]
    if '9 passed; 0 failed' not in checks[1].read_text(encoding='utf-8-sig') or checks[3].stat().st_size:
        raise ValueError('successful tests/fmt required')
    sources=['runtime/onnx/validate_native_cache_timing.py','runtime/onnx/prepare_native_cache_fixed.py',
        'runtime/onnx/benchmark_pilot.py','runtime/onnx/diagnose_native_cache.py','runtime/onnx/diagnose_native_repeats.py']
    save(args.output/'preregistration.json',{'utc':datetime.now(timezone.utc).isoformat(),'sources':[{'path':p,'sha256':sha(ROOT/p)} for p in sources],
        'assets':pre['assets'],'executable_sha256':sha(exe),'generation_sha256':sha(gen),'source_audit_sha256':sha(audit_path),
        'check_logs':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in checks],
        'prior_archive_index_sha256':sha(prior/'file-index.json'),'diagnostic_archive_index_sha256':sha(diagnostic/'file-index.json'),
        'configuration':config,'runs':runs,'seed':6791113,'case_ids':[v['id'] for v in cases],
        'processes':8,'forwards':84,'gate_observations_per_case':1,'resident_observations_per_case':2,
        'timeout_seconds':600,'memory_limit_bytes':limit,'host_before':host_state(),
        'acceptance':'ONNX<=1e-4,sum<=1e-6,judgment/tokens exact; old gate, diagnostic and within/between process probabilities<=1e-6; frozen Native<=1e-4 where available; no hidden/raw/input-ID diagnostic fields; exact cache/pool/resource metadata',
        'performance_acceptance':False,'formal_slo_acceptance':False,'production_backend_acceptance':False,
        'limitations':['same28 artificial inputs; three observations/case in two processes; resident14 requests is not long-running production history',
            'no per-request hidden/raw/input IDs; compute/tokenizer sources identical, tokens checked',
            'cache init CPU0 host-specific, main mask restored; compute placement/temperature/frequency/background uncontrolled',
            'numerical gate only, no warmup or Native/Tract latency comparison; old failed run and thresholds preserved']})
    rows=[];first={};active=None
    try:
        for run in runs:
            active=run['id'];job=args.output/(active+'.job.json')
            save(job,{'threads':4,'retained_f32':True,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':run['schedule']})
            print('START',active,flush=True);before=host_state()
            row=invoke([exe.resolve(),manifest.resolve(),job.resolve()],args.output,active,limit);after=host_state()
            events=[json.loads(line) for line in (args.output/(active+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
            validate_events(events,cases,policy,expected_threads=4);init=events[0]
            if len(events)!=len(run['schedule'])+2 or init['cache_diagnostic']!=config:raise ValueError('cache/event mismatch')
            if (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])!=(4,4,'4',3,1):raise ValueError('pool mismatch')
            if not init['retained_f32'] or (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])!=(320,3009572096,1,1044480):raise ValueError('retention mismatch')
            for e,item in zip(events[1:-1],run['schedule']):
                case=cases[item['case']]
                if e['case']!=case['id'] or e['warmup'] or e['physical_tokens']!=case['tokens']:raise ValueError('schedule/shape mismatch')
                if any(k in e for k in ['hidden_values','raw_logits','input_ids','processor_before','processor_after']):raise ValueError('diagnostic request instrumentation remains')
                name=e['case'];p=e['probabilities'];ref_error=delta(p,refs[name]) if name in refs else None
                old_error=delta(p,old[name]);diag_error=delta(p,diag[name]);repeat_error=delta(p,first[name]) if name in first else 0.0
                if max(old_error,diag_error,repeat_error)>1e-6 or (ref_error is not None and ref_error>1e-4):raise ValueError(f'Native gate failed: {name}')
                e.update(old_gate_probability_error=old_error,diagnostic_probability_error=diag_error,repeat_probability_error=repeat_error,frozen_native_probability_error=ref_error)
                first.setdefault(name,p)
            row.update(events=events,phase=run['phase'],chunk=run['chunk'],host_before=before,host_after=after)
            save(args.output/(active+'.validated.json'),row);rows.append(row);print('DONE',active,'forwards',len(run['schedule']),flush=True)
        summary={'processes':8,'forwards':84,'all_numeric_resource_gates_passed':True,'performance_acceptance':False,'formal_slo_acceptance':False,'production_backend_acceptance':False,'cases':{}}
        for case in cases:
            es=[e for r in rows for e in r['events'][1:-1] if e['case']==case['id']]
            resident=[e for r in rows if r['phase']=='resident' for e in r['events'][1:-1] if e['case']==case['id']]
            if len(es)!=3 or len(resident)!=2:raise ValueError('coverage mismatch')
            summary['cases'][case['id']]={'tokens':case['tokens'],'observations':3,'all_probabilities_exact':all(e['probabilities']==es[0]['probabilities'] for e in es),
                'within_resident_error':delta(resident[0]['probabilities'],resident[1]['probabilities']),
                **{key:max(e[field] for e in es) for key,field in [('max_old_gate_error','old_gate_probability_error'),('max_diagnostic_error','diagnostic_probability_error'),('max_repeat_error','repeat_probability_error'),('max_onnx_error','probability_max_abs_error')]}}
        for key in ['max_old_gate_error','max_diagnostic_error','max_repeat_error','max_onnx_error','within_resident_error']:summary[key]=max(v[key] for v in summary['cases'].values())
        save(args.output/'summary.json',summary);print('COMPLETE',flush=True)
    except Exception as error:
        save(args.output/'failure.json',{'active_run':active,'completed_runs':[r['run_id'] for r in rows],'error_type':type(error).__name__,'error':str(error),'host_after':host_state(),'numeric_acceptance':False,'performance_acceptance':False});raise


if __name__=='__main__':main()
