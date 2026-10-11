import ast,hashlib,json,math,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,validate_events
src=ROOT/'experiments/runs/observer-overhead-20261011';out=ROOT/'docs/research/jeff-onnx-tract/observer-overhead-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
assert not (src/'failure.json').exists()
accepted=ROOT/'docs/research/jeff-onnx-tract/cache-fixed-lengths-2026-10-11';observer=ROOT/'docs/research/jeff-onnx-tract/host-observer-2026-10-11'
for directory,key in [(accepted,'accepted_index_sha256'),(observer,'observer_acceptance_index_sha256')]:
    assert sha(directory/'file-index.json')==pre[key]
    for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/a['path'])==a['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
for name,key in [('benchmark_observer_overhead.py','script_sha256'),('observe_windows_host.py','observer_sha256'),('benchmark_pilot.py','helper_sha256'),('diagnose_native_repeats.py','host_helper_sha256')]:assert sha(ROOT/'runtime/onnx'/name)==pre[key]
assert pre['orders']==[['native4-off','native4-on','tract4-on','tract4-off'],['tract4-off','tract4-on','native4-on','native4-off']]
schedule=[{'case':0,'warmup':i<5} for i in range(8)];assert pre['schedule']==schedule and pre['planned_processes']==8 and pre['planned_forwards']==64 and pre['measured_per_backend_mode']==6
case=pre['cases'][0];assert case==next(c for c in json.loads((accepted/'reference-cases.json').read_text(encoding='utf-8')) if c['id']=='synthetic-ocr-ascii-3-128')
native_ref=json.loads((accepted/'old-native-gate-reference.json').read_text(encoding='utf-8'))[case['id']]
tract_ref=next(json.loads(l)['raw_logits'] for p in accepted.glob('gate-tract4-*.stdout.jsonl') for l in p.read_text(encoding='utf-8').splitlines() if json.loads(l).get('case')==case['id'])
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
def stats(v):
    a=sorted(v);n=len(a);assert n;return {'n':n,'median':a[math.ceil(n/2)-1],'p95':a[math.ceil(.95*n)-1],'min':a[0],'max':a[-1]}
def topology(s):return [(r['id'],r['group'],r['logical_processor'],r['core'],r['efficiency_class']) for r in s['cpu_sets']]
def host(s):
    assert s['power_status_raw']['ac_line_status']==1 and s['power_status_raw']['system_status_flag']==0
    assert s['active_scheme_guid']==pre['host_initial']['active_scheme_guid'] and s['observer_affinity']==pre['host_initial']['observer_affinity'] and topology(s)==topology(pre['host_initial'])
rows=[];native_history=[];observations=[]
for block,order in enumerate(pre['orders']):
    for config in order:
        name,mode=config.split('-');run=f'block{block}-{config}';native=name=='native4'
        raw=[json.loads(l) for l in (src/(run+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        row=json.loads((src/(run+'.validated.json')).read_text(encoding='utf-8'));process=json.loads((src/(run+'.process.json')).read_text(encoding='utf-8'));job=json.loads((src/(run+'.job.json')).read_text(encoding='utf-8'))
        assert job=={'threads':4,'retained_f32':True,'mode':'nnef-decluttered','profile_codegen':False,'profile_forward':False,'cache_init_cpu':pre['cache_configuration']['requested_cpu'],'cases':[case],'schedule':schedule}
        validate_events(raw,[case],policy,expected_threads=4);assert len(raw)==10
        init=raw[0]
        if native:
            assert init['cache_diagnostic']==pre['cache_configuration'] and (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
            assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
        else:assert init['executor_threads']==4 and init['multithread_mm']
        for e,item in zip(raw[1:-1],schedule):
            assert e['case']==case['id'] and e['warmup']==item['warmup'] and e['physical_tokens']==(128 if native else 512)
            if native:
                assert max(abs(a-b) for a,b in zip(e['probabilities'],native_ref))<=1e-6
                assert all(max(abs(a-b) for a,b in zip(e['probabilities'],p))<=1e-6 for p in native_history)
                native_history.append(e['probabilities']);e['compute_ns']=e['backbone_ns']+e['head_softmax_ns']
            else:assert e['raw_logits']==tract_ref and not e['forward_profile'];e['compute_ns']=e['forward_ns']+e['score_ns']
        assert raw==row['events'] and all(row[k]==v for k,v in process.items()) and (row['backend'],row['mode'],row['block'])==(name,mode,block)
        assert process['status']=='completed' and process['exit_code']==0 and process['guard_trigger'] is None and process['memory_samples']>0
        assert process['timeout_seconds']==600 and 0<process['parent_process_ns']<=600*10**9 and 0<process['peak_working_set_bytes']<=process['memory_limit_bytes']==pre['memory_limit_bytes']
        assert row['wrapper_wall_ns']>=row['parent_process_ns'] and 0<=row['parent_cpu_ns']<=16*row['wrapper_wall_ns']
        exe=ROOT/('.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe' if native else '.venv/tract-scatter-target/release/bench.exe');asset=ROOT/('models/jeff-rust-bundle-p3.json' if native else 'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar')
        assert process['command']==list(map(str,[exe.resolve(),asset.resolve(),(src/(run+'.job.json')).resolve()]))
        host(row['host_before']);host(row['host_after'])
        if mode=='on':
            hs=[json.loads(l) for l in (src/(run+'.host.jsonl')).read_text(encoding='utf-8').splitlines()];h=json.loads((src/(run+'.host-summary.json')).read_text(encoding='utf-8'))
            assert row['host_observation']==h and h['sampled_conditions_passed'] and not h['reasons'] and len(hs)==h['samples']>=2
            for item in hs:host(item)
            gaps=[(b['monotonic_ns']-a['monotonic_ns'])/1e9 for a,b in zip(hs,hs[1:])];assert all(0<g<=2.5 for g in gaps)
            assert h['maximum_gap_seconds']==max(gaps) and h['elapsed_seconds']==sum(gaps) and h['collection_ms_max']==max(x['collection_ns']/1e6 for x in hs)
            busy=[]
            for a,b in zip(hs,hs[1:]):
                x=a['system_cpu_100ns'];y=b['system_cpu_100ns'];total=y['kernel_including_idle']+y['user']-x['kernel_including_idle']-x['user'];idle=y['idle']-x['idle'];assert total>0 and 0<=idle<=total;busy.append(100*(total-idle)/total)
            assert h['system_busy_percent_min']==min(busy) and h['system_busy_percent_max']==max(busy)
            mhz=[p['current_mhz'] for x in hs for p in x['processor_power_os_report']];assert h['os_reported_current_mhz_min']==min(mhz) and h['os_reported_current_mhz_max']==max(mhz)
            for key in ['hardware_frequency_measured','temperature_available','compute_affinity_controlled','background_load_controlled','formal_slo_acceptance']:assert not h[key]
            observations.append({'run_id':run,**h})
        else:assert 'host_observation' not in row and not (src/(run+'.host.jsonl')).exists()
        rows.append(row)
assert s['processes']==8 and s['forwards']==64 and s['all_numeric_host_resource_gates_passed'] and not s['formal_slo_acceptance'] and not s['equivalence_acceptance']
assert s['max_onnx_probability_error']==max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1]) and s['native_repeat_exact']==all(p==native_history[0] for p in native_history)
assert len(list(src.glob('*.validated.json')))==8
for name in ['native4','tract4']:
    for mode in ['off','on']:
        selected=[r for r in rows if r['backend']==name and r['mode']==mode];es=[e for r in selected for e in r['events'][1:-1] if not e['warmup']]
        expected={**{k:stats([e[k]/1e9 for e in es]) for k in ['compute_ns','request_ns']},**{k:stats([r[k]/1e9 for r in selected]) for k in ['wrapper_wall_ns','parent_process_ns','parent_cpu_ns']},'startup_ns':stats([r['events'][0]['startup_ns']/1e9 for r in selected]),'peak_working_set_bytes':stats([r['peak_working_set_bytes'] for r in selected])}
        assert s['configurations'][name][mode]==expected and len(es)==6
    for block in range(2):
        pair={r['mode']:stats([e['compute_ns']/1e9 for e in r['events'][1:-1] if not e['warmup']]) for r in rows if r['backend']==name and r['block']==block}
        expected={'backend':name,'block':block,'compute_seconds':pair,'on_minus_off_median_seconds':pair['on']['median']-pair['off']['median'],'on_over_off_median_minus_one':pair['on']['median']/pair['off']['median']-1}
        assert expected in s['pairs']
assert len(s['pairs'])==4
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files'];assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files'];assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for name in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(accepted/name,out/name)
paths=['benchmark_observer_overhead.py','observe_windows_host.py','benchmark_pilot.py','diagnose_native_repeats.py']
save(out/'source-index.json',[{'path':'runtime/onnx/'+p,'sha256':sha(ROOT/'runtime/onnx'/p)} for p in paths])
for p in paths:shutil.copyfile(ROOT/'runtime/onnx'/p,out/p);ast.parse((out/p).read_text(encoding='utf-8'))
shutil.copyfile(__file__,out/'archive_observer_overhead.py');save(out/'host-observations.json',observations)
save(out/'validation.json',{'raw_schedule_numeric_pairwise_pool_resource_host_and_all_statistics_independently_checked':True,'processes':8,'forwards':64,'measured_per_backend_mode':6,'native_baseline_unchanged':127,'sibling_files_unchanged':21,'frozen_assets_and_prior_archives_unchanged':True,'formal_slo_acceptance':False,'equivalence_acceptance':False})
normalizations=[]
for p in out.glob('*.log'):
    b=p.read_bytes();n=b'\n'.join(l.rstrip(b' \t\r') for l in b.rstrip(b'\r\n').split(b'\n'))+b'\n' if b else b'';p.write_bytes(n)
    if n!=b:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(b).hexdigest(),'change':'archive whitespace/CRLF only; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Observer on/off performance pilot

Frozen cacheB Native4 and accepted Tract4. One old artificial128 fixture;
Native physical128, Tract512. Within-backend on/off comparisons only.
Two order-reversed pairs/backend,5 warmups+3 measured/session,8 children64
forwards,n6/mode/backend. Nearest-rank p95=max. All numeric/resource/host
gates and raw schedules/statistics independently checked. Parent CPU is
observer+existing process guard, excludes child CPU; wrapper wall includes
observer startup/finish. Off has boundary snapshots only. No temperature,
hardware clock, worker placement or background control.5% descriptive
screen only, no equivalence/performance adoption/formal SLO/quality claim.
Prior evidence and frozen Native/runtime/API/sibling preserved.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':s},indent=2))
