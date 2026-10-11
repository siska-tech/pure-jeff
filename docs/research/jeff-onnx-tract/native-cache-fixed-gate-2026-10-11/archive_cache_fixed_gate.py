import hashlib,json,math,pathlib,random,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,sha,save,validate_events
src=ROOT/'experiments/runs/native-cache-fixed-gate-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-cache-fixed-gate-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
failure=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'))
s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
assert not (src/'failure.json').exists()
for directory,key in [(prior,'prior_cache_archive_index_sha256'),(failure,'failure_archive_index_sha256')]:
    assert sha(directory/'file-index.json')==pre[key]
    for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/a['path'])==a['sha256']
for a in pre['assets']+pre['sources']:assert sha(ROOT/a['path'])==a['sha256']
exe=ROOT/'.venv/native-cache-diagnostic-target/release/native_cache_diagnostic.exe'
gen=ROOT/'.venv/native-cache-diagnostic-v2/generation.json'
assert sha(exe)==pre['executable_sha256'] and sha(gen)==pre['generation_sha256']
for a in json.loads(gen.read_text(encoding='utf-8'))['files']:assert sha(gen.parent/a['path'])==a['sha256']
assert sha(failure/'reference-cases.json')==pre['cases_sha256'] and sha(failure/'native-length-gate-probabilities.json')==pre['old_gate_sha256']
ref_path=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11/previous-native-probabilities.json'
assert sha(ref_path)==pre['native_refs_sha256']
cases=json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
old=json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
refs=json.loads(ref_path.read_text(encoding='utf-8'))
config=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))['configurations']['cacheB']
assert config==pre['configuration'] and pre['case_ids']==[c['id'] for c in cases] and len(cases)==28
assert (pre['processes'],pre['forwards'],pre['observations_per_case'],pre['threads'],pre['seed'])==(8,56,2,4,5781113)
assert not any(pre[k] for k in ['performance_acceptance','formal_slo_acceptance','production_backend_acceptance'])
probe=json.loads((src/'cache-probe.stdout.jsonl').read_text(encoding='utf-8'))
probe_record=json.loads((src/'cache-probe.process.json').read_text(encoding='utf-8'))
assert probe==config and probe_record['exit_code']==0 and probe_record['guard_trigger'] is None and probe_record['memory_samples']>0
assert probe_record['timeout_seconds']==30 and 0<probe_record['peak_working_set_bytes']<=pre['memory_limit_bytes']
planned=[]
for round_id,order in enumerate([[0,1,2,3],[3,2,1,0]]):
    for chunk in order:
        indices=list(range(7*chunk,7*chunk+7));random.Random(5781113+10*round_id+chunk).shuffle(indices)
        planned.append({'id':f'gate-{round_id}-chunk{chunk}','round':round_id,'chunk':chunk,'schedule':[{'case':i,'warmup':False} for i in indices]})
assert pre['runs']==planned
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
rows=[];first={};hosts=[]
def difference(a,b):
    assert len(a)==len(b)
    return max(abs(x-y) for x,y in zip(a,b))
def binary32(values):
    import struct
    return [struct.unpack('<f',struct.pack('<f',v))[0] for v in values]
for run in planned:
    name=run['id'];job=json.loads((src/(name+'.job.json')).read_text(encoding='utf-8'))
    record=json.loads((src/(name+'.process.json')).read_text(encoding='utf-8'))
    row=json.loads((src/(name+'.validated.json')).read_text(encoding='utf-8'))
    es=[json.loads(line) for line in (src/(name+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job=={'threads':4,'retained_f32':True,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':run['schedule']}
    validate_events(es,cases,policy,expected_threads=4);assert len(es)==9;init=es[0]
    assert init['cache_diagnostic']==config and config['affinity_restored'] and config['thread_mask_restored']==config['process_allowed_mask']
    assert (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
    assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
    for e,item in zip(es[1:-1],run['schedule']):
        case=cases[item['case']];assert e['case']==case['id'] and not e['warmup'] and e['physical_tokens']==e['effective_tokens']==case['tokens']
        assert e['input_ids']==[t for t,active in zip(case['inputs']['input_ids'],case['inputs']['attention_mask']) if active]
        for key,n in [('hidden_values',1024),('raw_logits',255)]:assert len(e[key])==n and all(math.isfinite(v) for v in e[key])
        assert all(config['process_allowed_mask']&(1<<e[k]) for k in ['processor_before','processor_after'])
        old_error=difference(e['probabilities'],old[e['case']])
        native_error=difference(e['probabilities'],refs[e['case']]) if e['case'] in refs else None
        repeat_error=difference(e['probabilities'],first[e['case']]['probabilities']) if e['case'] in first else 0.0
        assert old_error<=1e-6 and repeat_error<=1e-6 and (native_error is None or native_error<=1e-4)
        e.update(old_gate_probability_error=old_error,cross_process_probability_error=repeat_error,frozen_native_probability_error=native_error)
        first.setdefault(e['case'],e)
    assert es==row['events'] and row['round']==run['round'] and row['chunk']==run['chunk']
    assert all(row[k]==v for k,v in record.items())
    assert record['exit_code']==0 and record['guard_trigger'] is None and record['status']=='completed' and record['memory_samples']>0
    assert record['timeout_seconds']==600 and 0<record['parent_process_ns']<=600*10**9
    assert 0<record['peak_working_set_bytes']<=record['memory_limit_bytes']==pre['memory_limit_bytes']
    assert record['command']==list(map(str,[exe.resolve(),(ROOT/'models/jeff-rust-bundle-p3.json').resolve(),(src/(name+'.job.json')).resolve()]))
    before=row['host_before'];after=row['host_after'];a=before['system_cpu_100ns'];b=after['system_cpu_100ns']
    total=b['kernel_including_idle']+b['user']-a['kernel_including_idle']-a['user'];busy=100*(total-b['idle']+a['idle'])/total
    assert 0<=busy<=100
    hosts.append({'run_id':name,'before_power':before['power_status_raw'],'after_power':after['power_status_raw'],'system_wide_average_busy_percent':busy})
    rows.append(row)
assert len(rows)==8 and s['processes']==8 and s['forwards']==56 and s['all_28_case_numeric_cross_process_gates_passed'] and s['repeat_threshold']==1e-6 and s['cache_configuration']=='cacheB'
assert not any(s[k] for k in ['performance_acceptance','formal_slo_acceptance','production_backend_acceptance'])
for case in cases:
    observed=[(r['run_id'],e) for r in rows for e in r['events'][1:-1] if e['case']==case['id']]
    assert len(observed)==2 and observed[0][0]!=observed[1][0]
    a,b=[v[1] for v in observed]
    expected={'tokens':case['tokens'],'observations':2,'probabilities_exact':a['probabilities']==b['probabilities'],
        'hidden_exact':a['hidden_values']==b['hidden_values'],'raw_exact':a['raw_logits']==b['raw_logits'],
        'cross_process_probability_error':difference(a['probabilities'],b['probabilities']),
        'hidden_cross_process_error':difference(binary32(a['hidden_values']),binary32(b['hidden_values'])),
        'raw_cross_process_error':difference(binary32(a['raw_logits']),binary32(b['raw_logits'])),
        'max_old_gate_error':max(v['old_gate_probability_error'] for _,v in observed),
        'max_onnx_error':max(v['probability_max_abs_error'] for _,v in observed)}
    assert s['cases'][case['id']]==expected
for key,field in [('max_onnx_error','max_onnx_error'),('max_old_gate_error','max_old_gate_error'),('max_cross_process_probability_error','cross_process_probability_error')]:assert s[key]==max(v[field] for v in s['cases'].values())
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(prior/n,out/n)
save(out/'reference-cases.json',cases);save(out/'old-gate-reference.json',old);save(out/'frozen-native-reference.json',refs)
save(out/'source-index.json',pre['sources'])
for a in pre['sources']:shutil.copyfile(ROOT/a['path'],out/pathlib.Path(a['path']).name)
save(out/'host-observations.json',hosts)
check=json.loads((ROOT/'.venv/native-cache-fixed-validator-check.json').read_text(encoding='utf-8'))
assert check['source_sha256']==sha(ROOT/'runtime/onnx/validate_native_cache_fixed.py') and check['check_script_sha256']==sha(ROOT/'.venv/check_cache_fixed_validator.py') and len(check['checks'])==7
shutil.copyfile(ROOT/'.venv/native-cache-fixed-validator-check.json',out/'validator-check.json')
shutil.copyfile(ROOT/'.venv/check_cache_fixed_validator.py',out/'check_cache_fixed_validator.py')
save(out/'validation.json',{'independent_raw_numeric_input_hidden_raw_pool_cache_affinity_schedule_resource_and_summary_audit':True,
    'processes':8,'forwards':56,'cases':28,'independent_process_observations_per_case':2,
    'native_baseline_unchanged':127,'known_gitignore_difference_only':True,'sibling_files_unchanged':21,
    'prior_archives_and_frozen_assets_unchanged':True,'performance_acceptance':False,'formal_slo_acceptance':False,'production_backend_acceptance':False})
shutil.copyfile(__file__,out/'archive_cache_fixed_gate.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Native fixed-cache full28 numerical gate

Frozen instrumented cache diagnostic exe, cacheB init on verified logical CPU0,
main thread mask restored before pool/model/forward. Same step1113 FP32
text320/head1,4 compute threads,batch1. No runtime/API/source/exe changes.
Two passes over28 cases,7 per child, chunk order0/1/2/3 then3/2/1/0,
fixed shuffled input order =8 children/56 forwards. Each case observed in
two independent processes. No all-case within-process repeats or long
resident history. Existing ONNX1e-4,sum1e-6,judgment/tokens,input IDs,
finite hidden1024/raw255,pool/cache/affinity/resource gates enforced. Old
28-case Native gate and cross-process differences<=1e-6; frozen Native
references<=1e-4 where available. Thresholds and old failed evidence unchanged.
Independent raw validation includes chunk/order/coverage, CPU deltas, all
probability/hidden/raw differences and summary. Timing is diagnostic only.
Prior source/features/Rust checks and generated source are frozen in the
previous cache diagnostic archive, referenced by SHA256. This run accepts
only this instrumented condition/fixture set, not production backend,
uninstrumented performance build, long resident stability, formal SLO or
held-out recognition quality. Core placement/temperature/frequency/background
uncontrolled. CPU0 is host-specific, not a portable selection policy.
Native/API/sibling and all prior evidence unchanged. Python is dev-only.
License/NOTICE snapshot inherited; distribution acceptance remains open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'max_onnx_error':s['max_onnx_error'],'max_old_gate_error':s['max_old_gate_error'],'max_cross_process_probability_error':s['max_cross_process_probability_error']},indent=2))
