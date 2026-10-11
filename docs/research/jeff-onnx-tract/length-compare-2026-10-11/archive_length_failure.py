import hashlib,json,math,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,validate_events
def stats(values):
    ordered=sorted(values);n=len(ordered)
    return {'n':n,'median':ordered[math.ceil(n/2)-1],'p95':ordered[math.ceil(n*95/100)-1],'min':ordered[0],'max':ordered[-1]}
src=ROOT/'experiments/runs/length-compare-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'
length=ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/onnx/benchmark_length_compare.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
for directory in [prior,length,ROOT/'docs/research/jeff-onnx-tract/native-confirm-2026-10-11']:
    for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/item['path'])==item['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256'],a['path']
for item in json.loads((prior/'prior-thread-audit.json').read_text(encoding='utf-8'))['sources'].values():assert sha(item['path'])==item['sha256']
assert sha(prior/'preregistration.json')==pre['previous_native_preregistration_sha256']
assert sha(prior/'previous-native-probabilities.json')==pre['native_probabilities_sha256']
assert sha(prior/'prior-thread-audit.json')==pre['prior_audit_sha256']
assert sha(length/'oracle-oracle.json')==pre['oracle_sha256']
assert sha(length/'gate.stdout.jsonl')==pre['tract_raw_sha256']
cases=json.loads((length/'oracle-oracle.json').read_text(encoding='utf-8'))['cases']
for case in cases:case['count']=len(case['request']['candidates'])
refs=json.loads((prior/'previous-native-probabilities.json').read_text(encoding='utf-8'))
tract_refs={e['case']:e['raw_logits'] for e in [json.loads(line) for line in (length/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
gate_refs={e['case']:e['probabilities'] for e in [json.loads(line) for line in (src/'gate-native4.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
primary=[i for i,case in enumerate(cases) if 'variant' in case and case['candidate_count']!=8]
lengths=[128,256,384,511,512];rows=[];audits=[];violations=[]
assert pre['primary_indices']==primary and len(primary)==20 and len(cases)==28
assert pre['orders']==[['native4','tract4'],['tract4','native4'],['native4','tract4']]
expected_ids=['gate-native4','gate-tract4','resident-0-native4','resident-0-tract4','resident-1-tract4','resident-1-native4']
assert sorted(p.stem.replace('.process','') for p in src.glob('*.process.json'))==sorted(expected_ids)
for run_id in expected_ids:
    row=json.loads((src/(run_id+'.process.json')).read_text(encoding='utf-8'));name='native4' if run_id.endswith('native4') else 'tract4';native=name=='native4'
    job=json.loads((src/(run_id+'.job.json')).read_text(encoding='utf-8'))
    raw=[json.loads(line) for line in (src/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job['cases']==cases and job['threads']==4 and job['retained_f32'] is True
    assert job['mode']=='nnef-decluttered' and not job['profile_forward'] and not job['profile_codegen']
    validate_events(raw,cases,policy,expected_threads=4);init=raw[0]
    assert len(raw)==len(job['schedule'])+2
    if native:
        assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'])==(320,3009572096)
        assert (init['head_cached_tensors'],init['head_cached_bytes'])==(1,1044480)
        assert init['requested_threads']==init['rayon_pool_threads']==4 and init['candle_env_threads']=='4'
        assert init['expected_barrier_aux_workers']==3 and init['manifest_cpu_threads']==1
    else:assert init['executor_threads']==4 and init['multithread_mm'] is True
    for e,item in zip(raw[1:-1],job['schedule']):
        case=cases[item['case']];assert e['case']==case['id'] and e['warmup']==item['warmup']
        assert e['physical_tokens']==(case['tokens'] if native else 512)
        if native:
            delta=max(abs(a-b) for a,b in zip(e['probabilities'],refs[e['case']])) if e['case'] in refs else None
            repeat=max(abs(a-b) for a,b in zip(e['probabilities'],gate_refs[e['case']]))
            assert delta is None or delta<=1e-4
            e.update(native_probability_max_abs_error=delta,repeat_probability_max_abs_error=repeat,compute_ns=e['backbone_ns']+e['head_softmax_ns'])
            audit={'run_id':run_id,'case':e['case'],'iteration':e['iteration'],'warmup':e['warmup'],'tokens':e['effective_tokens'],
                'onnx_error':e['probability_max_abs_error'],'old_native_error':delta,'repeat_error':repeat,
                'repeat_passed':repeat<=1e-6,'actual':e['probabilities'],'gate_reference':gate_refs[e['case']]}
            audits.append(audit)
            if not audit['repeat_passed']:violations.append(audit)
        else:
            assert not e['forward_profile'] and e['raw_logits']==tract_refs[e['case']]
            e['compute_ns']=e['forward_ns']+e['score_ns']
    assert row['exit_code']==0 and row['guard_trigger'] is None and row['status']=='completed'
    assert row['timeout_seconds']==600 and row['memory_samples']>0 and row['parent_process_ns']<=600*10**9
    assert 0<row['peak_working_set_bytes']<=row['memory_limit_bytes']==pre['memory_limit_bytes']
    executable=ROOT/('.venv/native-threads-target/release/native_retained_bench.exe' if native else '.venv/tract-scatter-target/release/bench.exe')
    asset=ROOT/('models/jeff-rust-bundle-p3.json' if native else 'experiments/runs/nnef-pilot-20261010/jeff.decluttered.nnef.tar')
    assert row['command']==[str(executable.resolve()),str(asset.resolve()),str((src/(run_id+'.job.json')).resolve())]
    validated=src/(run_id+'.validated.json')
    if run_id!='resident-1-native4':
        stored=json.loads(validated.read_text(encoding='utf-8'));assert stored['events']==raw and stored['configuration']==name
    else:assert not validated.exists()
    if run_id.startswith('resident-'):
        block=int(run_id.split('-')[1]);assert job['schedule']==pre['schedules'][block]
        assert sorted(i['case'] for i in job['schedule'] if not i['warmup'])==primary
        assert sorted(cases[i['case']]['tokens'] for i in job['schedule'] if i['warmup'])==lengths
    else:assert job['schedule']==[{'case':i,'warmup':False} for i in range(28)]
    row.update(configuration=name,events=raw,registered_numeric_passed=run_id!='resident-1-native4');rows.append(row)
assert len(rows)==6 and sum(len(r['events'])-2 for r in rows)==156
assert len(violations)==6 and {v['run_id'] for v in violations}=={'resident-1-native4'}
assert sum(v['warmup'] for v in violations)==2 and max(v['repeat_error'] for v in violations)==3.546476364135742e-6
assert not (src/'summary.json').exists() and not list(src.glob('resident-2*'))
es=[e for r in rows for e in r['events'][1:-1]]
summary={'status':'stopped_registered_native_repeat_gate_failure','processes':6,'observed_forwards':156,'planned_forwards':206,
    'gate_forwards':56,'warmup_forwards':20,'measured_forwards':80,'unexecuted_forwards':50,
    'all_onnx_probability_judgment_token_gates_passed':True,'registered_numerical_passed':False,
    'max_onnx_probability_error':max(e['probability_max_abs_error'] for e in es),
    'max_old_native_probability_error':max(a['old_native_error'] for a in audits if a['old_native_error'] is not None),
    'max_native_repeat_error':max(a['repeat_error'] for a in audits),'native_repeat_violations':6,'affected_unique_cases':len({v['case'] for v in violations}),
    'native_repeat_passed_forwards':sum(a['repeat_passed'] for a in audits),'native_forwards':len(audits),
    'tract_raw_exact_forwards':sum(len(r['events'])-2 for r in rows if r['configuration']=='tract4'),
    'parent_harness_exit_code':1,'child_exit_codes':[r['exit_code'] for r in rows],'guard_triggers':0,
    'formal_slo_acceptance':False,'backend_adoption':False,'performance_acceptance':False,
    'timing_scope':'incomplete failed run, diagnostics only; no successful pooled comparison or optional stopping',
    'diagnostic_sessions':{}}
for row in rows:
    if not row['run_id'].startswith('resident'):continue
    measured=[e for e in row['events'][1:-1] if not e['warmup']]
    assert len(measured)==20
    keys=['compute_ns','request_ns']+(['backbone_ns','head_softmax_ns','tokenize_ns','policy_ns'] if row['configuration']=='native4' else ['forward_ns','score_ns','prepare_ns'])
    summary['diagnostic_sessions'][row['run_id']]={'registered_numeric_passed':row['registered_numeric_passed'],
        'lengths':{str(n):{k:stats([e[k]/1e9 for e in measured if e['effective_tokens']==n]) for k in keys} for n in lengths},
        'startup_stages_seconds':{k:row['events'][0][k]/1e9 for k in row['events'][0] if k.endswith('_ns')},
        'peak_working_set_bytes':row['peak_working_set_bytes']}
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
normal=json.loads((ROOT/'docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/tract/target/release/bench.exe')==normal['executable_sha256']
old_text=json.loads((ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'.venv/native-text-target/release/native_retained_bench.exe')==old_text['text_executable_sha256']
assert sha(ROOT/'.venv/native-retained-target/release/native_retained_bench.exe')==old_text['full_executable_sha256']
assert sha(ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe')=='d981d6b51ae708fd1adad0ac81845132ba8819afddf799f5afd275b7c83292c8'
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['cpu.json','os.json','power.txt']:shutil.copyfile(ROOT/'.venv'/('length-compare-host-'+n),out/('host-'+n))
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md','source-validation.json','dependency-feature-validation.json','prior-thread-audit.json']:shutil.copyfile(prior/n,out/n)
save(out/'reference-cases.json',cases);save(out/'previous-native-probabilities.json',refs)
save(out/'native-length-gate-probabilities.json',gate_refs);save(out/'previous-tract-raw.json',tract_refs)
save(out/'native-repeat-audit.json',audits);save(out/'repeat-violations.json',violations);save(out/'diagnostic-summary.json',summary)
save(out/'preservation.json',{'native_baseline_files':128,'native_unchanged':127,'expected_differences':diff,'sibling_files_unchanged':21,
    'frozen_native_executables_unchanged':True,'normal_tract_probe_unchanged':True,'accepted_tract_executable_and_174_sources_unchanged':True,
    'previous_thread_length_confirmation_archives_unchanged':True})
save(out/'validation.json',{'archive_audit_passed':True,'registered_numeric_gate_passed':False,'independent_raw_schedule_resource_probability_statistics_audit':True,
    'processes':6,'forwards':156,'native_repeat_violations':6,'all_onnx_probability_judgment_token_gates_passed':True,
    'tract_raw_exact_to_previous_gate':True,'child_failures':0,'guard_triggers':0,'harness_exit_code':1,
    'formal_slo_acceptance':False,'performance_acceptance':False,'third_pair_not_executed':True,'thresholds_unchanged':True})
save(out/'failure.json',{'run_id':'resident-1-native4','stage':'parent post-child validation','parent_exit_code':1,
    'error':'ValueError: Native repeat mismatch','first_failing_iteration':0,'all_25_child_forwards_completed_before_validation':True,
    'registered_repeat_tolerance':1e-6,'maximum_observed_repeat_error':summary['max_native_repeat_error'],'unexecuted_pair':2})
save(out/'harness-preflight-correction.json',{'phase':'before output directory creation or child launch',
    'initial_check':'incorrect right-padding expectation rejected existing left-padded oracle',
    'correction':'require attention_mask zero-prefix/one-suffix; no inference/timing or numerical threshold change',
    'benchmark_attempts_after_preregistration':1})
paths=['runtime/onnx/benchmark_length_compare.py','runtime/onnx/benchmark_pilot.py','runtime/onnx/prepare_native_threads.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths[:2]:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_length_failure.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Native4 / Tract4 length comparison: stopped on registered repeat gate

Frozen step1113 FP32 batch1 four-thread Native effective-length vs Tract
left-padded physical512. Planned three AB/BA/AB pairs, five mixed warmups+
twenty measured/session, n=12/length/configuration. ACTUAL six processes,
156 forwards=gate56+warmup20+measured80; third pair (50 forwards) NOT RUN.
All156 ONNX probability<=1e-4/sum<=1e-6/judgment/token gates passed, and
all78 Tract raw logits exactly match the previous length gate. Native repeat
<=1e-6 FAILED for six observations/four cases in resident-1-native4 (two
warmup/four measured), maximum3.546476364135742e-6. Child completed25 with
exit0; parent post-child validation failed at iteration0 with exit1. Other
five processes have validated records; failed Native process has raw/job/
process records and independent audit, no fabricated validated record.
Thresholds unchanged, no replacement run, no successful pooled comparison,
backend adoption or formal SLO. Diagnostic session/length stats n=4 include
the failed session explicitly, p95=max, not acceptance performance results.
Substantial timing drift also observed in both backends; causes unknown.
Two lightweight process snapshots during timing, cumulative CPU not usage.
No concurrent builds/tests/hash audits; background/thermals/AC/cache not
controlled. Shapes differ below512, request/startup verification scopes
unequal, no API E2E/cold campaign, lifetime peaks include mapped/shared pages.
Same artificial inputs; no held-out corpus or recognition labels. Eight-
candidate extras gate-only and lack128 cell. Native raw logits unavailable.
Independent raw/pool/cache/schedule/resource/probability/statistics audit;
all frozen assets, old thread/length/confirmation archives, Native/API and
sibling preserved. Nine Rust tests/clippy/fmt/source reproduction inherited
from frozen previous archive; NOTICE/distribution review remains open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'archive_audit':'PASS','registered_numeric_gate':'FAIL','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),
    'forwards':156,'max_onnx_error':summary['max_onnx_probability_error'],'max_repeat_error':summary['max_native_repeat_error']},indent=2))
