import hashlib,json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,stats,validate_events
src=ROOT/'experiments/runs/fp32-common512-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/fp32-common512-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11'
common=ROOT/'docs/research/jeff-onnx-tract/common512-pilot-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'))
summary=json.loads((src/'summary.json').read_text(encoding='utf-8'))
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['cpu.json','os.json','power.txt']:shutil.copyfile(ROOT/'.venv'/('fp32-common512-host-'+n),out/('host-'+n))
for n in ['reference-cases.json','previous-native-probabilities.json','LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:
    shutil.copyfile(prior/n,out/n)
shutil.copyfile(common/'previous-tract-raw.json',out/'previous-tract-raw.json')
shutil.copyfile(ROOT/'.venv/native-fp32-thread-audit.json',out/'thread-audit.json')
audit=json.loads((out/'thread-audit.json').read_text(encoding='utf-8'))
assert audit['compute_threads']==1 and audit['candle_core_nn_git_diff_exit_code']==0
assert audit['candle_commit']=='c68b24997319b8d76e5a4e775dab197c7f26322a'
assert sha(ROOT/'runtime/onnx/audit_native_threads.py')==audit['script_sha256']
for item in audit['sources'].values():assert sha(item['path'])==item['sha256']
for name in ['mkl','accelerate','cuda','metal']:assert 'candle-core feature "'+name+'"' not in audit['cargo_features']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256'],a['path']
assert sha(ROOT/'runtime/onnx/benchmark_fp32_common512.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
length=ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
assert sha(length/'oracle-oracle.json')==pre['oracle_sha256']
assert sha(length/'gate.stdout.jsonl')==pre['previous_raw_sha256']
for directory in [prior,common,length]:
    for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/item['path'])==item['sha256']
cases=json.loads((out/'reference-cases.json').read_text(encoding='utf-8'))
native_refs=json.loads((out/'previous-native-probabilities.json').read_text(encoding='utf-8'))
tract_refs=json.loads((out/'previous-tract-raw.json').read_text(encoding='utf-8'))
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
rows=[]
for path in sorted(src.glob('*.validated.json')):
    row=json.loads(path.read_text(encoding='utf-8'));job=json.loads((src/(row['run_id']+'.job.json')).read_text(encoding='utf-8'))
    raw=[json.loads(line) for line in (src/(row['run_id']+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job['cases']==cases and job['threads']==1 and job['retained_f32'] is True
    assert job['mode']=='nnef-decluttered' and not job['profile_forward'] and not job['profile_codegen']
    validate_events(raw,cases,policy,expected_threads=1)
    assert len(raw)==len(job['schedule'])+2
    if row['backend']=='native':
        assert raw[0]['retained_f32'] and (raw[0]['cached_tensors'],raw[0]['cached_bytes'])==(320,3009572096)
        assert (raw[0]['head_cached_tensors'],raw[0]['head_cached_bytes'])==(1,1044480)
    else:assert raw[0]['executor_threads']==1 and raw[0]['multithread_mm'] is True
    for event,item in zip(raw[1:-1],job['schedule']):
        case=cases[item['case']];assert event['case']==case['id'] and event['warmup']==item['warmup']
        assert event['physical_tokens']==(case['tokens'] if row['backend']=='native' else 512)
        if row['backend']=='native':
            assert event['probabilities']==native_refs[event['case']]
            event['compute_ns']=event['backbone_ns']+event['head_softmax_ns']
        else:
            assert not event['forward_profile'] and event['raw_logits']==tract_refs[event['case']]
            event['compute_ns']=event['forward_ns']+event['score_ns']
    assert raw==row['events'] and row['exit_code']==0 and row['guard_trigger'] is None
    if row['run_id'].startswith('resident-'):
        block=int(row['run_id'].split('-')[1]);assert job['schedule']==pre['schedules'][block]
    else:assert job['schedule']==[{'case':i,'warmup':False} for i in range(8)]
    rows.append(row)
assert len(rows)==8 and sum(len(r['events'])-2 for r in rows)==46
assert summary['processes']==8 and summary['forwards']==46 and summary['numerical_gate_passed']
assert max(e['probability_max_abs_error'] for r in rows for e in r['events'][1:-1])==summary['max_probability_error']
for backend in ['native','tract']:
    resident=[r for r in rows if r['backend']==backend and r['run_id'].startswith('resident')]
    es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    assert len(resident)==3 and len(es)==12 and all(e['physical_tokens']==e['effective_tokens']==512 for e in es)
    expected=summary['backends'][backend]
    for key,value in expected['stages_seconds'].items():assert stats([e[key]/1e9 for e in es])==value
    assert stats([r['events'][0]['startup_ns']/1e9 for r in resident])==expected['startup_seconds']
    assert stats([r['peak_working_set_bytes'] for r in resident])==expected['peak_working_set_bytes']
    for case in cases[4:]:
        items=[e for e in es if e['case']==case['id']];assert len(items)==3
        assert stats([e['compute_ns']/1e9 for e in items])==expected['inputs'][case['id']]
assert stats([r['events'][0]['retention_load_ns']/1e9 for r in rows if r['backend']=='native' and r['run_id'].startswith('resident')])==summary['backends']['native']['retention_load_seconds']
startup_stages={}
for backend in ['native','tract']:
    resident=[r for r in rows if r['backend']==backend and r['run_id'].startswith('resident')]
    startup_stages[backend]={k:stats([r['events'][0][k]/1e9 for r in resident]) for k in resident[0]['events'][0] if k.endswith('_ns')}
save(out/'startup-stages.json',{'scope':'post-measurement descriptive aggregation of initialized event; n=3, boundaries asymmetric','backends':startup_stages})
for block,pair in enumerate(summary['pairs']):
    assert pair['block']==block
    for backend in ['native','tract']:
        row=next(r for r in rows if r['run_id']==f'resident-{block}-{backend}')
        assert stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])==pair['compute_seconds'][backend]
    assert pair['tract_minus_native_session_median_seconds']==pair['compute_seconds']['tract']['median']-pair['compute_seconds']['native']['median']
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
normal=json.loads((ROOT/'docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/tract/target/release/bench.exe')==normal['executable_sha256']
assert sha(ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe')=='d981d6b51ae708fd1adad0ac81845132ba8819afddf799f5afd275b7c83292c8'
old=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'.venv/native-retained-target/release/native_retained_bench.exe')==old['full_executable_sha256']
save(out/'preservation.json',{'native_baseline_files':128,'native_unchanged':127,'expected_differences':diff,'sibling_files_unchanged':21,
    'frozen_native_full473_text320_executables_unchanged':True,'normal_tract_probe_unchanged':True,'accepted_tract_executable_and_174_sources_unchanged':True,
    'previous_text_common_length_archives_unchanged':True})
save(out/'validation.json',{'processes':8,'forwards':46,'gate_forwards':16,'warmup_forwards':6,'measured_forwards':24,
    'all_numeric_gates_passed':True,'native_probabilities_exact_to_frozen_native':True,'tract_raw_exact_to_frozen_four_thread_gate':True,
    'independent_raw_record_validation_and_statistics_recomputation':True,'max_probability_error':summary['max_probability_error'],
    'failures':0,'guard_triggers':0,'formal_slo_acceptance':False,'backend_adoption':False,'runtime_only_effect_claim':False})
paths=['runtime/onnx/audit_native_threads.py','runtime/onnx/benchmark_fp32_common512.py','runtime/onnx/benchmark_pilot.py',
    'runtime/rust/src/backbone.rs','runtime/rust/src/readout.rs','runtime/rust/src/prompt.rs','runtime/rust/src/tokenize.rs']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths[:3]:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_fp32_common512.py')
save(out/'development-notes.json',{'premeasurement_audit_attempt':'Cargo feature tree UTF-8 first decoded as cp932; UnicodeDecodeError before audit output/model launch. Explicit UTF-8 fixed before audit and preregistration. Zero performance samples affected.',
    'no_build_or_model_source_change':True,'prior_rust_tests':'text320 seven release tests and clippy/fmt preserved in previous archive; frozen exe reused without rebuild'})
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# FP32 retained common512 Native/Tract pilot

Frozen text320 Native FP32/head1 versus accepted Scatter Tract FP32 packed plan.
Same step1113, common effective/physical512, one compute thread, no padding.
Source/configuration thread audit captures Candle commit, clean diff, feature
tree and exact source excerpts/hashes. This does not assert one OS process
thread or measure active worker telemetry. Native wrapper forces both env vars
to 1; GEMM Parallelism::None, barrier auxiliary workers zero; DeltaNet serial.
Tract explicitly uses SingleThread. No existing executable/source rebuild.
Four goldens + four artificial requests gate both engines. Three AB/BA/AB
pairs, warmup1 + measured4, n=12/backend and n=3/input. Eight processes/46
forwards = gate16 + warmup6 + measured24. Numeric gates pass; Native frozen
probabilities exact; Tract raw exact to previous four-thread gate.
Raw/schedule/cache/resource records and all statistics independently checked.
Descriptive operating-configuration comparison, no backend adoption/SLO/speedup
or runtime-only claim. FP32 retention equalizes dtype, not packed layout,
algorithm, kernel boundaries, startup validation or API E2E. Lifetime peaks
include startup/mapped/shared pages, not private warm memory; n=3 incidental.
Nearest-rank n=12 p95=max, three pairs, one warmup, artificial content, no labels,
uncontrolled thermals/affinity/background/storage cache. No concurrent
builds/tests/hash audits during timings. Native/API/previous evidence/Tract
and sibling KazeNhanh preserved. No new runtime dependency or distribution
approval. Future Native thread matrix needs an independent wrapper and gates.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'validation':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':summary},indent=2))
