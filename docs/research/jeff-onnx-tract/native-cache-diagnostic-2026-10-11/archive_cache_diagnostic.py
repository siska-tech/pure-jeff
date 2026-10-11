import hashlib,json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,validate_events
from diagnose_native_cache import delta,f32
src=ROOT/'experiments/runs/native-cache-diagnostic-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'))
s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
failure=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
previous=ROOT/'docs/research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11'
for directory in [failure,previous]:
    for a in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/a['path'])==a['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
for p,key in [('runtime/onnx/diagnose_native_cache.py','script_sha256'),('runtime/onnx/prepare_native_cache_diagnostic.py','generator_sha256'),('runtime/onnx/benchmark_pilot.py','helper_sha256'),('runtime/onnx/diagnose_native_repeats.py','host_helper_sha256')]:assert sha(ROOT/p)==pre[key]
exe=ROOT/'.venv/native-cache-diagnostic-target/release/native_cache_diagnostic.exe'
gen=ROOT/'.venv/native-cache-diagnostic-v2/generation.json'
assert sha(exe)==pre['executable_sha256'] and sha(gen)==pre['generation_sha256']
generation=json.loads(gen.read_text(encoding='utf-8'))
for a in generation['files']:assert sha(gen.parent/a['path'])==a['sha256']
assert sha(src/'inventory.json')==pre['inventory_sha256']
inventory=json.loads((src/'inventory.json').read_text(encoding='utf-8'))
assert len(inventory)==pre['process_mask'].bit_count()
for item in inventory:
    cpu=item['requested_cpu'];name=f'probe-{cpu}'
    raw=json.loads((src/(name+'.stdout.jsonl')).read_text(encoding='utf-8'))
    record=json.loads((src/(name+'.process.json')).read_text(encoding='utf-8'))
    assert raw==item and item['actual_cpu_at_initialization']==cpu
    assert item['thread_mask_restored']==item['process_allowed_mask']==pre['process_mask'] and item['affinity_restored']
    assert record['exit_code']==0 and record['guard_trigger'] is None and record['memory_samples']>0 and record['timeout_seconds']==30
invalid=json.loads((src/'invalid-probe.json').read_text(encoding='utf-8'))
assert invalid['exit_code']!=0 and not invalid['stdout'] and 'CPU index exceeds single-group mask' in invalid['stderr']
all_cases=json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
cases=[next(c for c in all_cases if c['id']==name) for name in pre['case_ids']]
old=json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
failed={e['case']:e['probabilities'] for e in [json.loads(line) for line in (failure/'resident-1-native4.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
rows=[]
for block,order in enumerate(pre['orders']):
    for name in order:
        run_id=f'diagnostic-{block}-{name}';config=pre['configurations'][name]
        job=json.loads((src/(run_id+'.job.json')).read_text(encoding='utf-8'))
        record=json.loads((src/(run_id+'.process.json')).read_text(encoding='utf-8'))
        row=json.loads((src/(run_id+'.validated.json')).read_text(encoding='utf-8'))
        events=[json.loads(line) for line in (src/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        assert job=={'threads':4,'retained_f32':True,'cache_init_cpu':config['requested_cpu'],'cases':cases,'schedule':pre['schedules'][block]}
        validate_events(events,cases,policy,expected_threads=4);init=events[0]
        assert len(events)==6 and init['cache_diagnostic']==config and config in inventory
        assert (init['requested_threads'],init['rayon_pool_threads'],init['candle_env_threads'],init['expected_barrier_aux_workers'],init['manifest_cpu_threads'])==(4,4,'4',3,1)
        assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
        for e,i in zip(events[1:-1],job['schedule']):
            case=cases[i['case']]
            assert e['case']==case['id'] and not e['warmup'] and e['physical_tokens']==e['effective_tokens']==case['tokens']
            assert e['input_ids']==[token for token,active in zip(case['inputs']['input_ids'],case['inputs']['attention_mask']) if active]
            for key,size in [('hidden_values',1024),('raw_logits',255)]:
                assert len(e[key])==size and all(__import__('math').isfinite(v) for v in e[key])
            assert all(pre['process_mask']&(1<<e[key]) for key in ['processor_before','processor_after'])
            e['old_native4_gate_error']=delta(e['probabilities'],old[e['case']])
            e['failed_native4_session_error']=delta(e['probabilities'],failed[e['case']])
        assert events==row['events'] and row['configuration']==name and row['block']==block
        assert all(row[k]==v for k,v in record.items())
        assert record['exit_code']==0 and record['guard_trigger'] is None and record['status']=='completed' and record['memory_samples']>0
        assert record['timeout_seconds']==600 and 0<record['parent_process_ns']<=600*10**9
        assert 0<record['peak_working_set_bytes']<=record['memory_limit_bytes']==pre['memory_limit_bytes']
        assert record['command']==list(map(str,[exe.resolve(),(ROOT/'models/jeff-rust-bundle-p3.json').resolve(),(src/(run_id+'.job.json')).resolve()]))
        rows.append(row)
assert len(rows)==4 and s['observed_forwards']==16 and s['all_numeric_resource_gates_passed']
assert s['max_onnx_error']==max(e['probability_max_abs_error'] for row in rows for e in row['events'][1:-1])
for case in cases:
    groups={name:[e for r in rows if r['configuration']==name for e in r['events'][1:-1] if e['case']==case['id']] for name in pre['configurations']}
    entry=s['cases'][case['id']];assert entry['tokens']==case['tokens']
    for name,es in groups.items():
        assert len(es)==4
        assert entry['classes'][name]=={'observations':4,'probabilities_exact':all(e['probabilities']==es[0]['probabilities'] for e in es),
            'hidden_exact':all(e['hidden_values']==es[0]['hidden_values'] for e in es),'raw_exact':all(e['raw_logits']==es[0]['raw_logits'] for e in es),
            'max_old_gate_error':max(e['old_native4_gate_error'] for e in es),'max_failed_session_error':max(e['failed_native4_session_error'] for e in es)}
    a,b=groups['cacheA'][0],groups['cacheB'][0]
    for key,value in [('probability_class_delta',delta(a['probabilities'],b['probabilities'])),('hidden_class_delta',delta(f32(a['hidden_values']),f32(b['hidden_values']))),('raw_class_delta',delta(f32(a['raw_logits']),f32(b['raw_logits']))),('input_ids_equal',a['input_ids']==b['input_ids'])]:assert entry[key]==value
assert not any(s[key] for key in ['global_28_case_reacceptance','performance_acceptance','formal_slo_acceptance'])
# Independently reproduce dependency feature equality from full Cargo metadata.
before=json.loads((ROOT/'.venv/native-cache-before-metadata.json').read_text(encoding='utf-8'))
after=json.loads((ROOT/'.venv/native-cache-v2-metadata.json').read_text(encoding='utf-8'))
def features(meta):
    return {n['id']:n['features'] for n in meta['resolve']['nodes'] if n['id']!=meta['resolve']['root']}
assert features(before)==features(after) and len(features(after))==156
repro=ROOT/'.venv/native-cache-diagnostic-v2-reproduction'
assert len([p for p in gen.parent.rglob('*') if p.is_file()])==17
assert all(sha(p)==sha(repro/p.relative_to(gen.parent)) for p in gen.parent.rglob('*') if p.is_file())
for name in ['backbone.rs','weights.rs']:assert sha(gen.parent/'src'/name)==sha(ROOT/'.venv/native-threads-candidate/src'/name)
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
assert [a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']]==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(failure/n,out/n)
shutil.copytree(gen.parent,out/'generated-source')
paths=['runtime/onnx/diagnose_native_cache.py','runtime/onnx/prepare_native_cache_diagnostic.py','runtime/onnx/benchmark_pilot.py','runtime/onnx/diagnose_native_repeats.py','runtime/onnx/prepare_native_retained.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
for n in ['native-cache-v2-build.log','native-cache-v2-test.log','native-cache-v2-clippy.log','native-cache-v2-fmt.log','native-cache-source-validation.json','native-cache-feature-preflight-failure.json','prepare_native_cache_diagnostic-v1.py']:
    shutil.copyfile(ROOT/'.venv'/n,out/n)
save(out/'dependency-feature-audit.json',{'nonroot_packages_features_identical':156,'before_metadata_sha256':sha(ROOT/'.venv/native-cache-before-metadata.json'),'after_metadata_sha256':sha(ROOT/'.venv/native-cache-v2-metadata.json'),'features':features(after)})
save(out/'unmeasured-v1.json',{'generation_sha256':sha(ROOT/'.venv/native-cache-diagnostic-candidate/generation.json'),'executable_sha256':sha(ROOT/'.venv/native-cache-diagnostic-target/release/native_retained_bench.exe'),'model_forwards':0,'reason':'feature preflight changed default label; excluded before inference, v2 uses distinct bin name'})
save(out/'reference-cases.json',cases);save(out/'old-gate-reference.json',{c['id']:old[c['id']] for c in cases});save(out/'failed-session-reference.json',{c['id']:failed[c['id']] for c in cases})
save(out/'validation.json',{'raw_schedule_pool_resource_inputs_finite_hidden_raw_and_reference_deltas_independently_checked':True,'affinity_restore_and_cache_inventory_checked':True,'processes':4,'forwards':16,'features_identical_packages':156,'generated_files_reproduced':17,'native_baseline_unchanged':127,'known_gitignore_difference_only':True,'sibling_files_unchanged':21,'previous_archives_and_frozen_assets_unchanged':True,'performance_acceptance':False,'global_28_case_reacceptance':False})
shutil.copyfile(__file__,out/'archive_cache_diagnostic.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Controlled Native cache initialization diagnosis

Pin only the diagnostic main thread during explicit process CACHE_INFO init;
restore original thread mask before pool/model/forward. Enumerate every allowed
logical CPU first; choose one CPU for each of two observed cache classes.
AB/BA, two sessions/class, two cases, two repeats =16 forwards. No warmup or
performance/SLO acceptance. Hypothetical kernel_params are not actual GEMM
call telemetry. Hidden/raw JSON values normalized to binary f32 for deltas.
Input IDs exact, ONNX probability1e-4/sum1e-6/judgment/token/resource gates;
original repeat threshold1e-6 unchanged, no global28 reacceptance. Generated
backbone/weights and156 dependency feature sets unchanged,17 files reproduced.
Feature-label change in unmeasured v1 was rejected before inference and fixed
in v2, using a distinct executable. Raw logs, preregistration, independent
validator, generated source, references and license/NOTICE snapshots retained.
No historical CACHE_INFO telemetry; historical failure cause remains inference.
Core placement after restoration, temperature and frequency uncontrolled.
No API/runtime Python dependency change, recognition quality or distribution
approval. Existing failed evidence and all frozen assets remain preserved.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':s},indent=2))
