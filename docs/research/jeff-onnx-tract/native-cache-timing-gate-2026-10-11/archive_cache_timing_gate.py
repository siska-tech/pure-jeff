import hashlib,json,math,pathlib,random,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,sha,save,validate_events
src=ROOT/'experiments/runs/native-cache-timing-gate-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-cache-timing-gate-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-cache-fixed-gate-2026-10-11'
diagnostic=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
assert not (src/'failure.json').exists()
for directory,key in [(prior,'prior_archive_index_sha256'),(diagnostic,'diagnostic_archive_index_sha256')]:
    assert sha(directory/'file-index.json')==pre[key]
    for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/a['path'])==a['sha256']
for a in pre['sources']+pre['assets']+pre['check_logs']:assert sha(ROOT/a['path'])==a['sha256']
exe=ROOT/'.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe';gen=ROOT/'.venv/native-cache-fixed-candidate/generation.json'
assert sha(exe)==pre['executable_sha256'] and sha(gen)==pre['generation_sha256']
for a in json.loads(gen.read_text(encoding='utf-8'))['files']:assert sha(gen.parent/a['path'])==a['sha256']
audit_path=ROOT/'.venv/native-cache-fixed-source-audit.json';assert sha(audit_path)==pre['source_audit_sha256']
audit=json.loads(audit_path.read_text(encoding='utf-8'))
assert audit['dependency_packages_features_identical']==156 and audit['generated_files_identical']==16 and audit['cache_module_identical_to_diagnostic']
assert sha(ROOT/'.venv/native-cache-fixed-metadata.json')==audit['after_metadata_sha256']
meta=json.loads((ROOT/'.venv/native-cache-fixed-metadata.json').read_text(encoding='utf-8-sig'))
assert {n['id']:n['features'] for n in meta['resolve']['nodes'] if n['id']!=meta['resolve']['root']}==audit['features']
assert all(sha(p)==sha(ROOT/'.venv/native-cache-fixed-reproduction'/p.relative_to(gen.parent)) for p in gen.parent.rglob('*') if p.is_file())
for n in audit['unchanged_compute_source']:assert sha(gen.parent/'src'/n)==sha(ROOT/'.venv/native-threads-candidate/src'/n)
cases=json.loads((prior/'reference-cases.json').read_text(encoding='utf-8'));old=json.loads((prior/'old-gate-reference.json').read_text(encoding='utf-8'));refs=json.loads((prior/'frozen-native-reference.json').read_text(encoding='utf-8'))
diag={e['case']:e['probabilities'] for p in prior.glob('gate-0-*.stdout.jsonl') for e in [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()][1:-1]}
assert len(cases)==28 and set(diag)==set(old) and all(diag[k]==old[k] for k in old)
config=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))['configuration'];assert pre['configuration']==config
assert pre['case_ids']==[v['id'] for v in cases] and (pre['processes'],pre['forwards'],pre['seed'])==(8,84,6791113)
assert (pre['gate_observations_per_case'],pre['resident_observations_per_case'])==(1,2)
planned=[]
for phase,order in [('gate',[0,1,2,3]),('resident',[3,2,1,0])]:
    for chunk in order:
        schedule=[]
        for repeat in range(1 if phase=='gate' else 2):
            indices=list(range(7*chunk,7*chunk+7));random.Random(6791113+(100 if phase=='resident' else 0)+10*chunk+repeat).shuffle(indices)
            schedule.extend({'case':i,'warmup':False} for i in indices)
        planned.append({'id':f'{phase}-chunk{chunk}','phase':phase,'chunk':chunk,'schedule':schedule})
assert planned==pre['runs']
probe=json.loads((src/'cache-probe.stdout.jsonl').read_text(encoding='utf-8'));pr=json.loads((src/'cache-probe.process.json').read_text(encoding='utf-8'))
assert probe==config and pr['exit_code']==0 and pr['guard_trigger'] is None and pr['memory_samples']>0 and pr['timeout_seconds']==30
invalid=json.loads((src/'invalid-probe.json').read_text(encoding='utf-8'));assert invalid['exit_code']!=0 and not invalid['stdout'] and 'CPU index exceeds single-group mask' in invalid['stderr']
rows=[];first={};hosts=[];policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
def diff(a,b):
    assert len(a)==len(b)
    return max(abs(x-y) for x,y in zip(a,b))
for run in planned:
    name=run['id'];job=json.loads((src/(name+'.job.json')).read_text(encoding='utf-8'));record=json.loads((src/(name+'.process.json')).read_text(encoding='utf-8'));row=json.loads((src/(name+'.validated.json')).read_text(encoding='utf-8'))
    es=[json.loads(l) for l in (src/(name+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job=={'threads':4,'retained_f32':True,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':run['schedule']}
    validate_events(es,cases,policy,expected_threads=4);init=es[0];assert len(es)==len(run['schedule'])+2 and init['cache_diagnostic']==config
    assert (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
    assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
    for e,item in zip(es[1:-1],run['schedule']):
        case=cases[item['case']];assert e['case']==case['id'] and not e['warmup'] and e['physical_tokens']==e['effective_tokens']==case['tokens']
        assert not set(e).intersection(['hidden_values','raw_logits','input_ids','processor_before','processor_after'])
        name_id=e['case'];p=e['probabilities'];native=diff(p,refs[name_id]) if name_id in refs else None
        errors={'old_gate_probability_error':diff(p,old[name_id]),'diagnostic_probability_error':diff(p,diag[name_id]),'repeat_probability_error':diff(p,first[name_id]) if name_id in first else 0.0,'frozen_native_probability_error':native}
        assert all(errors[k]<=1e-6 for k in ['old_gate_probability_error','diagnostic_probability_error','repeat_probability_error']) and (native is None or native<=1e-4)
        e.update(errors);first.setdefault(name_id,p)
    assert es==row['events'] and row['phase']==run['phase'] and row['chunk']==run['chunk'] and all(row[k]==v for k,v in record.items())
    assert record['exit_code']==0 and record['guard_trigger'] is None and record['status']=='completed' and record['memory_samples']>0
    assert record['timeout_seconds']==600 and 0<record['parent_process_ns']<=600*10**9 and 0<record['peak_working_set_bytes']<=record['memory_limit_bytes']==pre['memory_limit_bytes']
    assert record['command']==list(map(str,[exe.resolve(),(ROOT/'models/jeff-rust-bundle-p3.json').resolve(),(src/(name+'.job.json')).resolve()]))
    a=row['host_before']['system_cpu_100ns'];b=row['host_after']['system_cpu_100ns'];total=b['kernel_including_idle']+b['user']-a['kernel_including_idle']-a['user'];busy=100*(total-b['idle']+a['idle'])/total;assert 0<=busy<=100
    hosts.append({'run_id':run['id'],'before_power':row['host_before']['power_status_raw'],'after_power':row['host_after']['power_status_raw'],'system_wide_average_busy_percent':busy});rows.append(row)
assert len(rows)==8 and s['processes']==8 and s['forwards']==84 and s['all_numeric_resource_gates_passed']
assert not any(v[k] for v in [pre,s] for k in ['performance_acceptance','formal_slo_acceptance','production_backend_acceptance'])
for case in cases:
    es=[e for r in rows for e in r['events'][1:-1] if e['case']==case['id']];resident=[e for r in rows if r['phase']=='resident' for e in r['events'][1:-1] if e['case']==case['id']]
    assert len(es)==3 and len(resident)==2
    # Also enforce every pair, not just each observation against the first gate.
    assert all(diff(a['probabilities'],b['probabilities'])<=1e-6 for a in es for b in es)
    expected={'tokens':case['tokens'],'observations':3,'all_probabilities_exact':all(e['probabilities']==es[0]['probabilities'] for e in es),'within_resident_error':diff(resident[0]['probabilities'],resident[1]['probabilities']),
        **{key:max(e[field] for e in es) for key,field in [('max_old_gate_error','old_gate_probability_error'),('max_diagnostic_error','diagnostic_probability_error'),('max_repeat_error','repeat_probability_error'),('max_onnx_error','probability_max_abs_error')]}}
    assert s['cases'][case['id']]==expected
for key in ['max_old_gate_error','max_diagnostic_error','max_repeat_error','max_onnx_error','within_resident_error']:assert s[key]==max(v[key] for v in s['cases'].values())
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files'];assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files'];assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
shutil.copytree(gen.parent,out/'generated-source')
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(prior/n,out/n)
for n in ['native-cache-fixed-build.log','native-cache-fixed-test.log','native-cache-fixed-clippy.log','native-cache-fixed-fmt.log','native-cache-fixed-source-audit.json','audit_cache_fixed_source.py']:shutil.copyfile(ROOT/'.venv'/n,out/n)
save(out/'source-index.json',pre['sources'])
for a in pre['sources']:shutil.copyfile(ROOT/a['path'],out/pathlib.Path(a['path']).name)
save(out/'reference-cases.json',cases);save(out/'old-gate-reference.json',old);save(out/'diagnostic-reference.json',diag);save(out/'frozen-native-reference.json',refs);save(out/'host-observations.json',hosts)
save(out/'validation.json',{'independent_raw_numeric_schedule_pool_cache_affinity_resource_reference_repeat_summary_audit':True,'request_diagnostic_fields_absent':True,'processes':8,'forwards':84,'cases':28,'resident_requests_per_process':14,'unchanged_compute_source':audit['unchanged_compute_source'],'generated_files_reproduced':16,'dependency_features_identical_packages':156,'native_baseline_unchanged':127,'known_gitignore_difference_only':True,'sibling_files_unchanged':21,'previous_archives_and_frozen_assets_unchanged':True,'performance_acceptance':False,'formal_slo_acceptance':False})
shutil.copyfile(__file__,out/'archive_cache_timing_gate.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b'';p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Cache-fixed timing wrapper numerical acceptance

New separate crate/target, same explicit cache module as diagnostic, original
backbone/weights/readout/threads source and per-request output. No hidden/raw/
input-ID/processor request instrumentation. Init still records cache metadata
and hypothetical params, not actual GEMM-call telemetry. Main thread restored
before pool/model/forward. Host-specific cacheB/CPU0 verified by probe.
Step1113,text320/head1 FP32,4 threads,batch1. Gate28 in4 children7 each, then
resident4 children7 cases twice =8 children84 forwards,3 observations/case
in two processes.14 requests/resident is not long production history.
ONNX1e-4,sum1e-6,judgment/tokens; old gate/accepted diagnostic/within and cross
process probabilities1e-6, frozen Native1e-4 where available. Thresholds and
old failed evidence unchanged. Numeric acceptance only: no warmup, latency
comparison, performance/SLO/backend adoption/recognition-quality acceptance.
Rust9 checks/clippy/fmt,156 package feature sets,16 reproduced files, exact
compute source equality, independent raw audit and license/NOTICE snapshots.
Core placement/temperature/frequency/background uncontrolled. Native/API and
sibling unchanged; Python dev-only. Portable core selection, long history,
formal measurement, real labels and distribution NOTICE remain pending.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'max_onnx_error':s['max_onnx_error'],'max_diagnostic_error':s['max_diagnostic_error'],'max_repeat_error':s['max_repeat_error'],'within_resident_error':s['within_resident_error']},indent=2))
