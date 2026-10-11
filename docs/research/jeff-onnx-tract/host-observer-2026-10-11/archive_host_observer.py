import ast,hashlib,json,math,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha
smoke=ROOT/'experiments/runs/host-observer-20261011';integration=ROOT/'experiments/runs/observed-backends-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/host-observer-2026-10-11'
pre=json.loads((integration/'preregistration.json').read_text());summary=json.loads((integration/'summary.json').read_text())
accepted=ROOT/'docs/research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11'
assert sha(accepted/'file-index.json')==pre['accepted_index_sha256']
for a in json.loads((accepted/'file-index.json').read_text()):assert sha(accepted/a['path'])==a['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
for file,key in [('validate_observed_backends.py','script_sha256'),('observe_windows_host.py','observer_sha256'),('benchmark_pilot.py','helper_sha256'),('diagnose_native_repeats.py','host_helper_sha256')]:assert sha(ROOT/'runtime/onnx'/file)==pre[key]
assert pre['planned_forwards']==6 and pre['schedule']==[{'case':0,'warmup':False}]*3 and pre['order']==['native4','tract4']
sp=json.loads((smoke/'preregistration.json').read_text());assert sp['duration_seconds']==30 and sp['interval_seconds']==1
assert sp['script_sha256']==pre['observer_sha256'] and not sp['settings_changed']
sample_counts={}
for folder,name in [(smoke,'preflight'),(smoke,'success'),(smoke,'nonzero'),(smoke,'deadline'),(integration,'native4'),(integration,'tract4')]:
    es=[json.loads(l) for l in (folder/(name+'.host.jsonl')).read_text().splitlines()];s=json.loads((folder/(name+'.host-summary.json')).read_text())
    assert len(es)>=2 and s['sampled_conditions_passed'] and not s['reasons'] and s['samples']==len(es)
    gaps=[(b['monotonic_ns']-a['monotonic_ns'])/1e9 for a,b in zip(es,es[1:])]
    assert all(0<g<=2.5 for g in gaps) and s['maximum_gap_seconds']==max(gaps) and s['elapsed_seconds']==sum(gaps)
    assert s['collection_ms_max']==max(e['collection_ns']/1e6 for e in es)
    assert all(e['power_status_raw']['ac_line_status']==1 and e['power_status_raw']['system_status_flag']==0 for e in es)
    assert len({e['active_scheme_guid'] for e in es})==1 and len({str(e['observer_affinity']) for e in es})==1
    topology=lambda e:[(r['id'],r['group'],r['logical_processor'],r['core'],r['efficiency_class']) for r in e['cpu_sets']]
    assert len({str(topology(e)) for e in es})==1 and len(topology(es[0]))==16
    busy=[]
    for a,b in zip(es,es[1:]):
        x=a['system_cpu_100ns'];y=b['system_cpu_100ns'];total=y['kernel_including_idle']+y['user']-x['kernel_including_idle']-x['user'];idle=y['idle']-x['idle']
        assert total>0 and 0<=idle<=total;busy.append(100*(total-idle)/total)
    assert s['system_busy_percent_min']==min(busy) and s['system_busy_percent_max']==max(busy)
    mhz=[p['current_mhz'] for e in es for p in e['processor_power_os_report']]
    assert s['os_reported_current_mhz_min']==min(mhz) and s['os_reported_current_mhz_max']==max(mhz)
    assert all(e['temperature_celsius'] is None for e in es)
    for key in ['temperature_available','hardware_frequency_measured','compute_affinity_controlled','background_load_controlled','formal_slo_acceptance']:assert not s[key]
    sample_counts[folder.name+'/'+name]=len(es)
assert sample_counts[smoke.name+'/preflight']==31
for name in ['success','nonzero','deadline']:
    r=json.loads((smoke/(name+'.process.json')).read_text())
    assert r['memory_samples']>0 and 0<r['peak_working_set_bytes']<=256*1024**2
    if name=='success':assert r['status']=='completed' and r['exit_code']==0 and r['guard_trigger'] is None
    elif name=='nonzero':assert r['status']=='failed' and r['exit_code']==7 and r['guard_trigger'] is None
    else:assert r['status']=='failed' and r['guard_trigger']=='deadline'
assert len(json.loads((smoke/'wrapper-validation.json').read_text()))==3
case=pre['cases'][0];native_ref=json.loads((accepted/'old-native-gate-reference.json').read_text())[case['id']]
tract_ref=next(json.loads(l)['raw_logits'] for p in accepted.glob('gate-tract4-*.stdout.jsonl') for l in p.read_text().splitlines() if json.loads(l).get('case')==case['id'])
errors=[];native_probs=[]
for name in ['native4','tract4']:
    raw=[json.loads(l) for l in (integration/(name+'.stdout.jsonl')).read_text().splitlines()]
    validated=json.loads((integration/(name+'.validated.json')).read_text());process=json.loads((integration/(name+'.process.json')).read_text())
    assert len(raw)==5 and raw[0]['event']=='initialized' and raw[-1]['event']=='completed'
    assert process['status']=='completed' and process['exit_code']==0 and process['guard_trigger'] is None and process['memory_samples']>0
    assert 0<process['parent_process_ns']<=600*10**9 and 0<process['peak_working_set_bytes']<=process['memory_limit_bytes']==pre['memory_limit_bytes']
    assert validated['host_observation']==json.loads((integration/(name+'.host-summary.json')).read_text())
    init=raw[0]
    if name=='native4':
        assert init['cache_diagnostic']==pre['cache_configuration'] and (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
        assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
    else:assert init['executor_threads']==4 and init['multithread_mm']
    for e in raw[1:-1]:
        p=e['probabilities'];assert len(p)==len(case['expected_probabilities']) and all(math.isfinite(v) and 0<=v<=1 for v in p) and abs(sum(p)-1)<=1e-6
        err=max(abs(a-b) for a,b in zip(p,case['expected_probabilities']));assert err<=1e-4;errors.append(err)
        ranked=sorted(range(len(p)),key=lambda i:-p[i]);best=p[ranked[0]];margin=best-p[ranked[1]]
        judge={'kind':'selected','candidate_id':case['request']['candidates'][ranked[0]]['id']} if margin>0 and best>=.7 and margin>=.1 else {'kind':'abstained'}
        assert judge==case['expected_judgment'] and e['effective_tokens']==e['physical_tokens']==512 and e['case']==case['id'] and not e['warmup']
        if name=='native4':
            assert e['judgment']==judge and max(abs(a-b) for a,b in zip(p,native_ref))<=1e-6;native_probs.append(p)
        else:assert e['raw_logits']==tract_ref and not e['forward_profile']
        e.update(probability_max_abs_error=err,judgment_match=True)
    assert raw==validated['events']
assert all(p==native_probs[0] for p in native_probs)
assert summary=={'forwards':6,'all_numeric_and_sampled_host_conditions_passed':True,'max_onnx_probability_error':max(errors),'native_repeat_exact':True,'performance_acceptance':False,'formal_slo_acceptance':False}
tests=(smoke/'tests.log').read_text(encoding='utf-8-sig');assert 'Ran 7 tests' in tests and 'OK' in tests
assert json.loads((smoke/'thermal-query.json').read_text(encoding='utf-8-sig'))['status']=='unavailable'
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text())['files'];assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text())['files'];assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
shutil.copytree(smoke,out/'smoke');shutil.copytree(integration,out/'integration')
for name in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(accepted/name,out/name)
paths=['observe_windows_host.py','test_observe_windows_host.py','validate_observed_backends.py','benchmark_pilot.py','diagnose_native_repeats.py']
save(out/'source-index.json',[{'path':'runtime/onnx/'+p,'sha256':sha(ROOT/'runtime/onnx'/p)} for p in paths])
for p in paths:shutil.copyfile(ROOT/'runtime/onnx'/p,out/p);ast.parse((out/p).read_text())
shutil.copyfile(ROOT/'.venv/run_host_wrapper_smoke.py',out/'run_host_wrapper_smoke.py');shutil.copyfile(__file__,out/'archive_host_observer.py')
normalizations=[]
for p in out.rglob('*.log'):
    b=p.read_bytes();n=b'\n'.join(l.rstrip(b' \t\r') for l in b.rstrip(b'\r\n').split(b'\n'))+b'\n' if b else b'';p.write_bytes(n)
    if n!=b:normalizations.append({'path':p.relative_to(out).as_posix(),'original_sha256':hashlib.sha256(b).hexdigest(),'change':'archive whitespace/CRLF only; ignored original retained'})
save(out/'log-archival.json',normalizations)
save(out/'validation.json',{'raw_telemetry_numeric_and_resource_independently_checked':True,'samples':sample_counts,'forwards':6,'unit_tests':7,'guard_cases':3,'baseline_files_unchanged':127,'sibling_files_unchanged':21,'settings_changed':False,'performance_acceptance':False,'formal_slo_acceptance':False})
(out/'README.md').write_text('''# Windows host observer integration evidence

Read-only development telemetry. 30-second smoke, 3 child lifecycle/guard
checks, 7 unit tests, frozen Native/Tract each3 forwards on one old512 fixture.
Raw samples/stats and numerical/resource conditions independently checked.
No performance acceptance, overhead calibration, hardware clock/temperature,
worker placement control, background control, quality or formal SLO claim.
Original sandbox temporary-directory tests failed before file writes; moved
test temp directories into workspace .venv and all7 passed. Initial backend
reference lookup failed before output registration/inference; fixed to search
all archived gate chunks. No numerical threshold or reference was changed.
Temperature CIM query unavailable (access denied), preserved as missing.
System busy includes unrelated processes; frequency values are OS reports.
CPU sets describe topology/park state, not which cores executed a forward.
Sampled AC/scheme stability cannot rule out changes between samples.
Existing runtime/API and frozen assets untouched. Python is development-only.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text())),'validation':json.loads((out/'validation.json').read_text())},indent=2))
