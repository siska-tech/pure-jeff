import hashlib,json,math,pathlib,random,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,validate_events
src=ROOT/'experiments/runs/cache-fixed-lengths-20261011';out=ROOT/'docs/research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
assert not (src/'failure.json').exists()
prior=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11';length=ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11';accepted=ROOT/'docs/research/jeff-onnx-tract/native-cache-timing-gate-2026-10-11'
for directory in [prior,length,accepted]:
    for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/a['path'])==a['sha256']
assert sha(accepted/'file-index.json')==pre['cache_fixed_acceptance_index_sha256']
for path,key in [('runtime/onnx/benchmark_cache_fixed_lengths.py','script_sha256'),('runtime/onnx/benchmark_pilot.py','helper_sha256'),('runtime/onnx/diagnose_native_repeats.py','host_helper_sha256')]:assert sha(ROOT/path)==pre[key]
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
for a in json.loads((prior/'prior-thread-audit.json').read_text(encoding='utf-8'))['sources'].values():assert sha(a['path'])==a['sha256']
for path,key in [(prior/'preregistration.json','previous_native_preregistration_sha256'),(prior/'previous-native-probabilities.json','native_probabilities_sha256'),(prior/'prior-thread-audit.json','prior_audit_sha256'),(length/'oracle-oracle.json','oracle_sha256'),(length/'gate.stdout.jsonl','tract_raw_sha256')]:assert sha(path)==pre[key]
cases=json.loads((src/'reference-cases.json').read_text(encoding='utf-8'))
expected_cases=json.loads((length/'oracle-oracle.json').read_text(encoding='utf-8'))['cases']
for case in expected_cases:case['count']=len(case['request']['candidates'])
assert cases==expected_cases and len(cases)==28
refs=json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'));old=json.loads((accepted/'old-gate-reference.json').read_text(encoding='utf-8'))
tract_refs={e['case']:e['raw_logits'] for e in [json.loads(l) for l in (length/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
config=json.loads((accepted/'preregistration.json').read_text(encoding='utf-8'))['configuration'];assert config==pre['cache_configuration']
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
primary=[i for i,c in enumerate(cases) if 'variant' in c and c['candidate_count']!=8];lengths=[128,256,384,511,512];variants=sorted({cases[i]['variant'] for i in primary})
assert len(primary)==20 and pre['primary_indices']==primary and pre['lengths']==lengths and pre['seed']==7901113
assert pre['orders']==[['native4','tract4'],['tract4','native4'],['native4','tract4']]
assert pre['planned_processes']==14 and pre['planned_forwards']==206 and pre['gate_chunks_per_configuration']==4 and not pre['formal_slo_acceptance'] and not pre['held_out_input_data']
schedules=[]
for block in range(3):
    warm=[next(i for i in primary if cases[i]['tokens']==n and cases[i]['variant']==variants[block]) for n in lengths]
    measured=primary.copy();random.Random(7901113+block).shuffle(measured)
    schedules.append([{'case':i,'warmup':True} for i in warm]+[{'case':i,'warmup':False} for i in measured])
assert pre['schedules']==schedules
planned=[]
for name in ['native4','tract4']:
    for chunk in range(4):planned.append((f'gate-{name}-{chunk}',name,[{'case':i,'warmup':False} for i in range(7*chunk,7*chunk+7)],True))
for block,order in enumerate(pre['orders']):
    for name in order:planned.append((f'resident-{block}-{name}',name,schedules[block],False))
assert sorted(p.name for p in src.glob('*.validated.json'))==sorted(run+'.validated.json' for run,_,_,_ in planned)
rows=[];gate={};history={};hosts=[]
def diff(a,b):
    assert len(a)==len(b)
    return max(abs(x-y) for x,y in zip(a,b))
def stats(values):
    a=sorted(values);n=len(a);assert n
    return {'n':n,'median':a[math.ceil(n/2)-1],'p95':a[math.ceil(n*.95)-1],'min':a[0],'max':a[-1]}
for run,name,schedule,is_gate in planned:
    native=name=='native4';record=json.loads((src/(run+'.process.json')).read_text(encoding='utf-8'));row=json.loads((src/(run+'.validated.json')).read_text(encoding='utf-8'));job=json.loads((src/(run+'.job.json')).read_text(encoding='utf-8'))
    es=[json.loads(l) for l in (src/(run+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job=={'threads':4,'retained_f32':True,'mode':'nnef-decluttered','profile_codegen':False,'profile_forward':False,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':schedule}
    validate_events(es,cases,policy,expected_threads=4);init=es[0];assert len(es)==len(schedule)+2
    if native:
        assert init['cache_diagnostic']==config and (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
        assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
    else:assert init['executor_threads']==4 and init['multithread_mm']
    for e,item in zip(es[1:-1],schedule):
        case=cases[item['case']];assert e['case']==case['id'] and e['warmup']==item['warmup'] and e['physical_tokens']==(case['tokens'] if native else 512)
        if native:
            native_error=diff(e['probabilities'],refs[e['case']]) if e['case'] in refs else None;assert native_error is None or native_error<=1e-4
            old_error=diff(e['probabilities'],old[e['case']]);assert old_error<=1e-6
            if is_gate:gate[e['case']]=e['probabilities']
            repeat=diff(e['probabilities'],gate[e['case']]);assert repeat<=1e-6
            assert all(diff(e['probabilities'],p)<=1e-6 for p in history.get(e['case'],[]));history.setdefault(e['case'],[]).append(e['probabilities'])
            e.update(old_gate_probability_error=old_error,native_probability_max_abs_error=native_error,repeat_probability_max_abs_error=repeat,compute_ns=e['backbone_ns']+e['head_softmax_ns'])
            assert not set(e).intersection(['hidden_values','raw_logits','input_ids','processor_before','processor_after'])
        else:
            assert not e['forward_profile'] and e['raw_logits']==tract_refs[e['case']];e['compute_ns']=e['forward_ns']+e['score_ns']
    assert es==row['events'] and row['configuration']==name and all(row[k]==v for k,v in record.items())
    assert record['exit_code']==0 and record['guard_trigger'] is None and record['status']=='completed' and record['memory_samples']>0
    assert record['timeout_seconds']==600 and 0<record['parent_process_ns']<=600*10**9 and 0<record['peak_working_set_bytes']<=record['memory_limit_bytes']==pre['memory_limit_bytes']
    executable=ROOT/('.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe' if native else '.venv/tract-scatter-target/release/bench.exe')
    asset=ROOT/('models/jeff-rust-bundle-p3.json' if native else 'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar')
    assert record['command']==list(map(str,[executable.resolve(),asset.resolve(),(src/(run+'.job.json')).resolve()]))
    for moment in ['host_before','host_after']:assert row[moment]['power_status_raw']['ac_line_status']==1 and row[moment]['power_status_raw']['system_status_flag']==0
    a=row['host_before']['system_cpu_100ns'];b=row['host_after']['system_cpu_100ns'];total=b['kernel_including_idle']+b['user']-a['kernel_including_idle']-a['user'];busy=100*(total-b['idle']+a['idle'])/total;assert 0<=busy<=100
    hosts.append({'run_id':run,'before_power':row['host_before']['power_status_raw'],'after_power':row['host_after']['power_status_raw'],'system_wide_average_busy_percent':busy});rows.append(row)
assert len(rows)==s['processes']==14 and sum(len(r['events'])-2 for r in rows)==s['forwards']==206 and s['numerical_passed'] and not s['formal_slo_acceptance']
es=[e for r in rows for e in r['events'][1:-1]];nes=[e for r in rows if r['configuration']=='native4' for e in r['events'][1:-1]]
assert s['max_onnx_probability_error']==max(e['probability_max_abs_error'] for e in es)
assert s['max_native_probability_error']==max(e['native_probability_max_abs_error'] for e in nes if e['native_probability_max_abs_error'] is not None)
assert s['max_native_repeat_error']==max(e['repeat_probability_max_abs_error'] for e in nes)
for name in ['native4','tract4']:
    resident=[r for r in rows if r['configuration']==name and r['run_id'].startswith('resident')];measured=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    keys=['compute_ns','request_ns']+(['backbone_ns','head_softmax_ns','tokenize_ns','policy_ns'] if name=='native4' else ['forward_ns','score_ns','prepare_ns'])
    expected={'lengths':{str(n):{k:stats([e[k]/1e9 for e in measured if e['effective_tokens']==n]) for k in keys} for n in lengths},
        'startup_stages_seconds':{k:stats([r['events'][0][k]/1e9 for r in resident]) for k in resident[0]['events'][0] if k.endswith('_ns')},
        'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in resident]),
        'inputs':{cases[i]['id']:stats([e['compute_ns']/1e9 for e in measured if e['case']==cases[i]['id']]) for i in primary}}
    assert s['configurations'][name]==expected and all(v['compute_ns']['n']==12 for v in expected['lengths'].values())
for block in range(3):
    pair={name:{str(n):stats([e['compute_ns']/1e9 for r in rows if r['run_id']==f'resident-{block}-{name}' for e in r['events'][1:-1] if not e['warmup'] and e['effective_tokens']==n]) for n in lengths} for name in ['native4','tract4']}
    assert s['blocks'][block]=={'block':block,'compute_seconds':pair,'tract4_minus_native4_median_seconds':{str(n):pair['tract4'][str(n)]['median']-pair['native4'][str(n)]['median'] for n in lengths}}
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files'];assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files'];assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(accepted/n,out/n)
paths=['runtime/onnx/benchmark_cache_fixed_lengths.py','runtime/onnx/benchmark_length_compare.py','runtime/onnx/benchmark_pilot.py','runtime/onnx/diagnose_native_repeats.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(ROOT/'.venv/prepare_cache_fixed_length_harness.py',out/'prepare_cache_fixed_length_harness.py')
patch_bytes=(ROOT/'.venv/cache-fixed-length-harness.patch').read_bytes()
save(out/'cache-fixed-length-harness.patch.json',{'original_sha256':hashlib.sha256(patch_bytes).hexdigest(),'encoding':'utf-8','content':patch_bytes.decode('utf-8')})
save(out/'host-observations.json',hosts);save(out/'old-native-gate-reference.json',old)
save(out/'validation.json',{'independent_raw_schedule_pool_cache_affinity_power_resource_numeric_pairwise_repeat_and_all_statistics_audit':True,'processes':14,'forwards':206,'native_forwards':103,'tract_forwards':103,'warm_measured_samples_per_length_per_backend':12,'nearest_rank_p95_is_maximum':True,'native_baseline_unchanged':127,'known_gitignore_difference_only':True,'sibling_files_unchanged':21,'previous_archives_and_frozen_assets_unchanged':True,'formal_slo_acceptance':False,'production_backend_acceptance':False})
shutil.copyfile(__file__,out/'archive_cache_fixed_lengths.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b'';p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Cache-fixed Native4 / Tract4 length pilot

Frozen numerically accepted Native timing exe, cacheB CPU0 initialization only,
main mask restored before model/pool/forward. Frozen accepted Tract Scatter
exe/NNEF plan. Step1113, FP32 resident,batch1,4 threads. Native effective length,
Tract left-padded physical512: shape/layout/algorithm and startup/request
scopes unequal. Operational configuration comparison, no runtime-only claim.
Gate28/backend in4 children each, then3 AB/BA/AB resident pairs,5 mixed-length
warmups+20 measured/session =14 children206 forwards,103/backend. Each length
128/256/384/511/512 n12/backend, n3/input. Nearest-rank median,p95=max.
Existing ONNX1e-4,sum1e-6,judgment/tokens, Native references1e-4, old Native gate
and pairwise repeats1e-6, Tract raw exactly previous length gate. AC connected
and battery saver off required at each child boundary; system CPU snapshots
include other processes. Compute affinity/temperature/frequency/background
uncontrolled, same old artificial inputs, partially balanced order, no holdout.
Lifetime peak n3 includes startup/mapped/shared pages, not warm private memory
or storage-cold campaign. No backend adoption/API E2E/formal SLO/quality claim.
All raw/stats independently audited; original failed evidence/thresholds,
Native/API and sibling unchanged. Python dev-only, distribution NOTICE open.
The source diff is stored as JSON-escaped UTF-8 with its original byte hash;
decoding content.encode('utf-8') reconstructs the original patch bytes.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':s},indent=2))
