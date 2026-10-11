import hashlib,json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,stats,validate_events
src=ROOT/'experiments/runs/native-text-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-retained-2026-10-11'
gen=ROOT/'.venv/native-text-candidate';repro=ROOT/'.venv/native-text-reproduction'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));summary=json.loads((src/'summary.json').read_text(encoding='utf-8'))
generation=json.loads((gen/'generation.json').read_text(encoding='utf-8'))
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['cpu.json','os.json','power.txt']:shutil.copyfile(ROOT/'.venv'/('native-text-host-'+n),out/('host-'+n))
for n in ['build','test','clippy','fmt']:shutil.copyfile(ROOT/'.venv'/('native-text-'+n+'.log'),out/(n+'.log'))
assert '7 passed; 0 failed' in (out/'test.log').read_text(encoding='utf-8')
assert not (out/'fmt.log').read_bytes()
assert 'warning:' not in (out/'build.log').read_text(encoding='utf-8')
assert 'warning:' not in (out/'clippy.log').read_text(encoding='utf-8')
assert sha(ROOT/'runtime/onnx/benchmark_native_text.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
assert sha(ROOT/'runtime/onnx/prepare_native_text.py')==generation['generator_sha256']
assert sha(ROOT/'runtime/onnx/prepare_native_retained.py')==generation['anchor_helper_sha256']
assert sha(gen/'generation.json')==pre['generation_sha256']
assert sha(prior/'generation.json')==pre['previous_generation_sha256']==generation['previous_generation_sha256']
for mode,target in [('full','native-retained'),('text','native-text')]:
    assert sha(ROOT/f'.venv/{target}-target/release/native_retained_bench.exe')==pre[mode+'_executable_sha256']
assert (gen/'generation.json').read_bytes()==(repro/'generation.json').read_bytes()
assert len(generation['files'])==11
for item in generation['files']:
    p=gen/item['path'];assert sha(p)==item['sha256']==sha(repro/item['path'])
    target=out/'generated'/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for p in ['Cargo.toml','Cargo.lock','src/main.rs','src/backbone.rs','src/readout.rs']:
    assert (gen/p).read_bytes()==(prior/'generated'/p).read_bytes()
for path,digest in generation['sources'].items():assert sha(ROOT/path)==digest
for item in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):assert sha(prior/item['path'])==item['sha256']
for n in ['generation.json']:shutil.copyfile(gen/n,out/n)
for n in ['reference-cases.json','previous-native-probabilities.json','weight-inventory.json','LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:
    shutil.copyfile(prior/n,out/n)
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
assert sha(prior/'reference-cases.json')==pre['reference_cases_sha256']
assert sha(prior/'previous-native-probabilities.json')==pre['previous_native_probabilities_sha256']
assert sha(prior/'weight-inventory.json')==generation['inventory_sha256']
cases=json.loads((prior/'reference-cases.json').read_text(encoding='utf-8'));refs=json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'))
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy'];rows=[]
for path in sorted(src.glob('*.validated.json')):
    row=json.loads(path.read_text(encoding='utf-8'));job=json.loads((src/(row['run_id']+'.job.json')).read_text(encoding='utf-8'))
    raw=[json.loads(line) for line in (src/(row['run_id']+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job['cases']==cases and job['retained_f32'] is True
    validate_events(raw,cases,policy,expected_threads=1)
    assert len(raw)==len(job['schedule'])+2 and raw[0]['retained_f32'] is True
    expected=(473,3411943680) if row['mode']=='full' else (320,3009572096)
    assert (raw[0]['cached_tensors'],raw[0]['cached_bytes'])==expected
    assert (raw[0]['head_cached_tensors'],raw[0]['head_cached_bytes'])==(1,1044480)
    for event,item in zip(raw[1:-1],job['schedule']):
        case=cases[item['case']]
        assert event['case']==case['id'] and event['warmup']==item['warmup']
        assert event['physical_tokens']==case['tokens'] and event['probabilities']==refs[event['case']]
        event['compute_ns']=event['backbone_ns']+event['head_softmax_ns']
    assert raw==row['events'] and row['exit_code']==0 and row['guard_trigger'] is None
    if row['run_id'].startswith('resident-'):
        block=int(row['run_id'].split('-')[1]);assert job['schedule']==pre['schedules'][block]
    else:assert job['schedule']==[{'case':i,'warmup':False} for i in range(8)]
    rows.append(row)
assert len(rows)==8 and sum(len(r['events'])-2 for r in rows)==46
assert summary['processes']==8 and summary['forwards']==46 and summary['numeric_passed'] and summary['probabilities_exact_to_frozen_native']
assert max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1])==summary['max_probability_error']
for mode in ['full','text']:
    resident=[r for r in rows if r['mode']==mode and r['run_id'].startswith('resident')]
    es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    assert len(resident)==3 and len(es)==12 and all(e['physical_tokens']==e['effective_tokens']==512 for e in es)
    expected=summary['modes'][mode]
    for key,value in expected['stages_seconds'].items():assert stats([e[key]/1e9 for e in es])==value
    for field,key in [('startup_seconds','startup_ns'),('retention_load_seconds','retention_load_ns')]:assert stats([r['events'][0][key]/1e9 for r in resident])==expected[field]
    assert stats([r['peak_working_set_bytes'] for r in resident])==expected['peak_working_set_bytes']
    for case in cases[4:]:
        items=[e for e in es if e['case']==case['id']];assert len(items)==3
        assert stats([e['compute_ns']/1e9 for e in items])==expected['inputs'][case['id']]
for block,pair in enumerate(summary['pairs']):
    assert pair['block']==block
    for mode in ['full','text']:
        row=next(r for r in rows if r['run_id']==f'resident-{block}-{mode}')
        assert stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])==pair['compute_seconds'][mode]
        assert row['peak_working_set_bytes']==pair['peak_working_set_bytes'][mode]
    assert pair['text_minus_full_median_seconds']==pair['compute_seconds']['text']['median']-pair['compute_seconds']['full']['median']
    assert pair['text_minus_full_peak_bytes']==pair['peak_working_set_bytes']['text']-pair['peak_working_set_bytes']['full']
assert summary['local_memory_acceptance']==(all(p['text_minus_full_peak_bytes']<0 for p in summary['pairs']) and summary['modes']['text']['peak_working_set_bytes']['max']<summary['modes']['full']['peak_working_set_bytes']['max'])
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
tract=json.loads((ROOT/'docs/research/jeff-onnx-tract/common512-pilot-2026-10-11/preregistration.json').read_text(encoding='utf-8'))
for a in tract['assets']:
    if a['path'].endswith('bench.exe') or 'tract-scatter-candidate' in a['path']:assert sha(ROOT/a['path'])==a['sha256']
normal=json.loads((ROOT/'docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/tract/target/release/bench.exe')==normal['executable_sha256']
assert sha(ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe')=='d981d6b51ae708fd1adad0ac81845132ba8819afddf799f5afd275b7c83292c8'
save(out/'preservation.json',{'native_baseline_files':128,'native_unchanged':127,'expected_differences':diff,'sibling_files_unchanged':21,
    'previous_full_cache_evidence_and_executable_unchanged':True,'frozen_native_executable_unchanged':True,'normal_tract_probe_unchanged':True,'accepted_tract_executable_and_174_sources_unchanged':True})
save(out/'source-validation.json',{'generated_files_reproduced':11,'backbone_readout_wrapper_cargo_manifest_lock_byte_exact_to_full_candidate':True,'release_rust_tests_passed':7,'build_clippy_fmt_passed':True,'dependencies_unchanged':True})
save(out/'validation.json',{'processes':8,'forwards':46,'gate_forwards':16,'warmup_forwards':6,'measured_forwards':24,'all_numeric_gates_passed':True,
    'all_probabilities_exact_to_frozen_native':True,'independent_raw_record_validation_and_statistics_recomputation':True,'max_probability_error':summary['max_probability_error'],
    'local_memory_acceptance':summary['local_memory_acceptance'],'latency_acceptance':False,'formal_slo_acceptance':False,'failures':0,'guard_triggers':0})
paths=['runtime/onnx/prepare_native_text.py','runtime/onnx/benchmark_native_text.py','runtime/onnx/prepare_native_retained.py','runtime/onnx/benchmark_pilot.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths]+[{'path':p,'sha256':h} for p,h in generation['sources'].items() if p not in paths])
for p in paths[:2]:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_native_text.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Native text320 FP32 retention pilot

Pinned full473 executable versus text320 candidate; same equations, wrapper,
Cargo manifest/lock and head1. Only retained model tensor selection changes.
Exact full473 inventory required; missing/duplicate/unexpected names rejected.
Eleven generated files independently reproduced; seven Rust tests, clippy, fmt.
Eight processes, 46 forwards: gate16, warmup6, measured24. Common512, one thread,
three AB/BA/AB pairs, one warmup plus four mixed measured requests/session.
All candidate probabilities exact to frozen Native; ONNX numeric gates pass.
Independent raw/schedule/cache/resource validation and statistics recomputation.
Local MEMORY-ONLY acceptance: all paired lifetime peaks and pooled maximum
decrease. Startup and warm latency are descriptive, no latency acceptance/SLO.
Lifetime peak includes startup mmap/conversion, not warm private memory.
n=12/mode, per-input n=3; nearest-rank p95=max; only three independent pairs.
Synthetic input, uncontrolled thermals/affinity/background/storage cache.
No concurrent builds/tests/hash audits during timings. Original Native/API,
previous full-cache candidate/evidence, Tract and sibling KazeNhanh preserved.
No new runtime dependency or distribution approval. Real quality remains open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'validation':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':summary},indent=2))
