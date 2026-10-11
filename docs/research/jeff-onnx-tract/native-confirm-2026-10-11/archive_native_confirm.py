import hashlib,itertools,json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,stats,validate_events
src=ROOT/'experiments/runs/native-confirm-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-confirm-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'
length=ROOT/'docs/research/jeff-onnx-tract/length-pilot-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));summary=json.loads((src/'summary.json').read_text(encoding='utf-8'))
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['cpu.json','os.json','power.txt']:shutil.copyfile(ROOT/'.venv'/('native-confirm-host-'+n),out/('host-'+n))
for n in ['reference-cases.json','previous-native-probabilities.json','LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md','source-validation.json','dependency-feature-validation.json']:
    shutil.copyfile(prior/n,out/n)
shutil.copyfile(prior/'prior-thread-audit.json',out/'prior-thread-audit.json')
assert sha(prior/'preregistration.json')==pre['previous_native_preregistration_sha256']
assert sha(prior/'reference-cases.json')==pre['reference_cases_sha256']
assert sha(prior/'previous-native-probabilities.json')==pre['native_probabilities_sha256']
assert sha(length/'gate.stdout.jsonl')==pre['tract_raw_sha256']
assert sha(prior/'prior-thread-audit.json')==pre['prior_audit_sha256']
for directory in [prior,length]:
    for item in json.loads((directory/'file-index.json').read_text(encoding='utf-8')):assert sha(directory/item['path'])==item['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256'],a['path']
for item in json.loads((prior/'prior-thread-audit.json').read_text(encoding='utf-8'))['sources'].values():assert sha(item['path'])==item['sha256']
assert sha(ROOT/'runtime/onnx/benchmark_native_confirm.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
cases=json.loads((out/'reference-cases.json').read_text(encoding='utf-8'));refs=json.loads((out/'previous-native-probabilities.json').read_text(encoding='utf-8'))
tract_refs={e['case']:e['raw_logits'] for e in [json.loads(line) for line in (length/'gate.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]}
save(out/'previous-tract-raw.json',{case['id']:tract_refs[case['id']] for case in cases})
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
configurations={'native2':2,'native4':4,'tract4':4};rows=[];gate_refs={}
for name in ['native2','native4']:
    for e in [json.loads(line) for line in (src/('gate-'+name+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()][1:-1]:gate_refs[(name,e['case'])]=e['probabilities']
for path in sorted(src.glob('*.validated.json')):
    row=json.loads(path.read_text(encoding='utf-8'));name=row['configuration'];t=configurations[name];native=name.startswith('native')
    job=json.loads((src/(row['run_id']+'.job.json')).read_text(encoding='utf-8'));raw=[json.loads(line) for line in (src/(row['run_id']+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job['cases']==cases and job['threads']==t and job['retained_f32'] is True
    assert job['mode']=='nnef-decluttered' and not job['profile_forward'] and not job['profile_codegen']
    validate_events(raw,cases,policy,expected_threads=t);init=raw[0]
    assert len(raw)==len(job['schedule'])+2
    if native:
        assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'])==(320,3009572096)
        assert (init['head_cached_tensors'],init['head_cached_bytes'])==(1,1044480)
        assert init['requested_threads']==init['rayon_pool_threads']==t and init['candle_env_threads']==str(t)
        assert init['expected_barrier_aux_workers']==t-1 and init['manifest_cpu_threads']==1
    else:assert init['executor_threads']==4 and init['multithread_mm'] is True
    for e,item in zip(raw[1:-1],job['schedule']):
        case=cases[item['case']];assert e['case']==case['id'] and e['warmup']==item['warmup']
        assert e['physical_tokens']==(case['tokens'] if native else 512)
        if native:
            delta=max(abs(a-b) for a,b in zip(e['probabilities'],refs[e['case']]))
            repeat=max(abs(a-b) for a,b in zip(e['probabilities'],gate_refs[(name,e['case'])]))
            assert delta<=1e-4 and repeat<=1e-6
            e.update(native_probability_max_abs_error=delta,repeat_probability_max_abs_error=repeat,compute_ns=e['backbone_ns']+e['head_softmax_ns'])
        else:
            assert not e['forward_profile'] and e['raw_logits']==tract_refs[e['case']]
            e['compute_ns']=e['forward_ns']+e['score_ns']
    assert raw==row['events'] and row['exit_code']==0 and row['guard_trigger'] is None
    if row['run_id'].startswith('resident-'):
        block=int(row['run_id'].split('-')[1]);assert job['schedule']==pre['schedules'][block]
    else:assert job['schedule']==[{'case':i,'warmup':False} for i in range(8)]
    rows.append(row)
assert pre['orders']==[list(p) for p in itertools.permutations(configurations)]
assert all([order[pos] for order in pre['orders']].count(name)==2 for pos in range(3) for name in configurations)
assert len(rows)==21 and sum(len(r['events'])-2 for r in rows)==114
es=[e for r in rows for e in r['events'][1:-1]];native_es=[e for r in rows if r['configuration'].startswith('native') for e in r['events'][1:-1]]
assert summary['processes']==21 and summary['forwards']==114 and summary['numerical_passed']
assert max(e['probability_max_abs_error'] for e in es)==summary['max_onnx_probability_error']
assert max(e['native_probability_max_abs_error'] for e in native_es)==summary['max_native_probability_error']
assert max(e['repeat_probability_max_abs_error'] for e in native_es)==summary['max_native_repeat_error']
numeric={}
for name in configurations:
    resident=[r for r in rows if r['configuration']==name and r['run_id'].startswith('resident')];measured=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    assert len(resident)==6 and len(measured)==24 and all(e['physical_tokens']==e['effective_tokens']==512 for e in measured)
    expected=summary['configurations'][name]
    for key,value in expected['stages_seconds'].items():assert stats([e[key]/1e9 for e in measured])==value
    for key,value in expected['startup_stages_seconds'].items():assert stats([r['events'][0][key]/1e9 for r in resident])==value
    assert stats([r['peak_working_set_bytes'] for r in resident])==expected['peak_working_set_bytes']
    for case in cases[4:]:
        items=[e for e in measured if e['case']==case['id']];assert len(items)==6
        assert stats([e['compute_ns']/1e9 for e in items])==expected['inputs'][case['id']]
    if name.startswith('native'):
        all_es=[e for r in rows if r['configuration']==name for e in r['events'][1:-1]]
        numeric[name]={'forwards':len(all_es),'exact_to_frozen_native':sum(e['probabilities']==refs[e['case']] for e in all_es),'max_frozen_error':max(e['native_probability_max_abs_error'] for e in all_es),'max_repeat_error':max(e['repeat_probability_max_abs_error'] for e in all_es)}
for block,entry in enumerate(summary['blocks']):
    assert entry['block']==block
    for name in configurations:
        row=next(r for r in rows if r['run_id']==f'resident-{block}-{name}')
        assert stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])==entry['compute_seconds'][name]
    pair=entry['compute_seconds']
    assert entry['native4_minus_native2_median_seconds']==pair['native4']['median']-pair['native2']['median']
    assert entry['tract4_minus_native4_median_seconds']==pair['tract4']['median']-pair['native4']['median']
a=summary['configurations']['native2']['stages_seconds']['compute_ns'];b=summary['configurations']['native4']['stages_seconds']['compute_ns']
assert summary['local_native4_confirmation']==(all(block['native4_minus_native2_median_seconds']<0 for block in summary['blocks']) and b['median']<a['median'] and b['p95']<a['p95'])
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
normal=json.loads((ROOT/'docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/tract/target/release/bench.exe')==normal['executable_sha256']
text=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11';old_text=json.loads((text/'preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'.venv/native-text-target/release/native_retained_bench.exe')==old_text['text_executable_sha256']
assert sha(ROOT/'.venv/native-retained-target/release/native_retained_bench.exe')==old_text['full_executable_sha256']
assert sha(ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe')=='d981d6b51ae708fd1adad0ac81845132ba8819afddf799f5afd275b7c83292c8'
save(out/'preservation.json',{'native_baseline_files':128,'native_unchanged':127,'expected_differences':diff,'sibling_files_unchanged':21,
    'frozen_native_full473_text320_thread_executables_unchanged':True,'normal_tract_probe_unchanged':True,'accepted_tract_executable_and_174_sources_unchanged':True,'previous_thread_and_length_archives_unchanged':True})
save(out/'numeric-by-configuration.json',numeric)
save(out/'validation.json',{'processes':21,'forwards':114,'gate_forwards':24,'warmup_forwards':18,'measured_forwards':72,'all_numeric_gates_passed':True,
    'native_repeat_tolerance':1e-6,'tract_raw_exact_to_frozen_gate':True,'pool_configuration_verified':True,
    'independent_raw_record_validation_and_statistics_recomputation':True,'local_native4_confirmation':summary['local_native4_confirmation'],
    'formal_slo_acceptance':False,'backend_adoption':False,'held_out_input_data':False,'failures':0,'guard_triggers':0})
paths=['runtime/onnx/benchmark_native_confirm.py','runtime/onnx/benchmark_pilot.py','runtime/onnx/prepare_native_threads.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths[:2]:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_native_confirm.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Independent Native2/4 confirmation and Tract4 comparison

Frozen Native thread wrapper and accepted Scatter Tract exe, no rebuild/source
change. Native text320/head1 FP32, Tract FP32 packed plan, common512 text-only.
Three configurations in all six permutations; each position occurs twice.
One warmup + four measured/session, n=24/configuration and n=6/input. Twenty-one
processes/114 forwards = gate24 + warmup18 + measured72. New independent
sessions/seed after exploratory matrix, SAME artificial inputs, no held-out
input corpus or recognition quality labels. Nearest-rank p95=second-largest.
Native frozen probabilities tolerance1e-4, setting repeat1e-6; Tract raw exact
to frozen four-thread gate; all ONNX probability/judgment/tokens gates pass.
Global Native Rayon pool/Candle settings and Tract executor4 verified.
Raw/schedule/cache/pool/resource validation and all statistics independently
recomputed. Native4 warm confirmation only if all six block medians and pooled
median/p95 below Native2; no optional stopping or post-hoc threshold change.
Native4/Tract4 is descriptive operating-configuration comparison; no runtime-only
effect, adoption, API E2E or formal SLO. Algorithms/layout/kernel boundaries and
startup verification/request scopes differ. Lifetime peak includes startup/
mapped/shared memory, n=6 incidental; not warm private memory/cold campaign.
Thermals/affinity/background/storage cache uncontrolled; one warmup/six blocks.
No concurrent builds/tests/hash audits during timings. Nine Rust tests and
clippy/fmt/source reproduction inherited from hash-frozen previous archive.
Previous executables/source/archives, Native/API and sibling KazeNhanh preserved.
No new runtime dependency or distribution approval; NOTICE audit still open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'validation':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':summary},indent=2))
