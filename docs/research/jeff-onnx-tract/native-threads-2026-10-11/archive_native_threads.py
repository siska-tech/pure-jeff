import hashlib,json,pathlib,shutil,sys,tomllib
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,stats,validate_events
src=ROOT/'experiments/runs/native-threads-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'
prior=ROOT/'docs/research/jeff-onnx-tract/native-text-2026-10-11'
gen=ROOT/'.venv/native-threads-candidate';repro=ROOT/'.venv/native-threads-reproduction'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'));summary=json.loads((src/'summary.json').read_text(encoding='utf-8'))
generation=json.loads((gen/'generation.json').read_text(encoding='utf-8'))
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['cpu.json','os.json','power.txt']:shutil.copyfile(ROOT/'.venv'/('native-threads-host-'+n),out/('host-'+n))
for n in ['build','test','clippy','fmt']:shutil.copyfile(ROOT/'.venv'/('native-threads-'+n+'.log'),out/(n+'.log'))
assert '9 passed; 0 failed' in (out/'test.log').read_text(encoding='utf-8')
assert not (out/'fmt.log').read_bytes()
assert 'warning:' not in (out/'build.log').read_text(encoding='utf-8')
assert 'warning:' not in (out/'clippy.log').read_text(encoding='utf-8')
assert sha(ROOT/'runtime/onnx/benchmark_native_threads.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
assert sha(ROOT/'runtime/onnx/prepare_native_threads.py')==generation['generator_sha256']
assert sha(ROOT/'runtime/onnx/prepare_native_retained.py')==generation['anchor_helper_sha256']
assert sha(gen/'generation.json')==pre['generation_sha256']
assert sha(ROOT/'.venv/native-threads-target/release/native_retained_bench.exe')==pre['executable_sha256']
assert (gen/'generation.json').read_bytes()==(repro/'generation.json').read_bytes()
assert len(generation['files'])==13
for item in generation['files']:
    p=gen/item['path'];assert sha(p)==item['sha256']==sha(repro/item['path'])
    target=out/'generated'/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
for p in ['src/backbone.rs','src/readout.rs','src/weights.rs','src/text_inventory.rs']:assert (gen/p).read_bytes()==(prior/'generated'/p).read_bytes()
restored=(gen/'src/main.rs').read_text(encoding='utf-8').replace('mod threads;\n','')
restored=restored.replace('    let requested_threads = threads::configure(&job)?;', '    std::env::set_var("CANDLE_NUM_THREADS", "1");\n    std::env::set_var("RAYON_NUM_THREADS", "1");')
restored=restored.replace('"threads":candle_core::utils::get_num_threads(),"requested_threads":requested_threads,"rayon_pool_threads":rayon::current_num_threads(),"candle_env_threads":std::env::var("CANDLE_NUM_THREADS")?,"expected_barrier_aux_workers":requested_threads-1,"manifest_cpu_threads":header.policy.cpu_threads,','"threads":candle_core::utils::get_num_threads(),')
assert restored==(prior/'generated/src/main.rs').read_text(encoding='utf-8')
for p,h in generation['sources'].items():assert sha(ROOT/p)==h
old_lock=tomllib.loads((prior/'generated/Cargo.lock').read_text(encoding='utf-8'));new_lock=tomllib.loads((gen/'Cargo.lock').read_text(encoding='utf-8'))
assert [p for p in old_lock['package'] if p['name']!='kaze_judge_native_bench']==[p for p in new_lock['package'] if p['name']!='kaze_judge_native_bench']
old_root=next(p for p in old_lock['package'] if p['name']=='kaze_judge_native_bench');new_root=next(p for p in new_lock['package'] if p['name']=='kaze_judge_native_bench')
assert sorted(new_root['dependencies'])==sorted(old_root['dependencies']+['rayon'])
for item in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):assert sha(prior/item['path'])==item['sha256']
shutil.copyfile(gen/'generation.json',out/'generation.json')
for n in ['reference-cases.json','previous-native-probabilities.json','LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(prior/n,out/n)
audit=ROOT/'docs/research/jeff-onnx-tract/fp32-common512-2026-10-11/thread-audit.json'
assert sha(audit)==pre['audit_sha256'];shutil.copyfile(audit,out/'prior-thread-audit.json')
for item in json.loads(audit.read_text(encoding='utf-8'))['sources'].values():assert sha(item['path'])==item['sha256']
for a in pre['assets']:assert sha(ROOT/a['path'])==a['sha256']
assert sha(prior/'reference-cases.json')==pre['reference_cases_sha256']
assert sha(prior/'previous-native-probabilities.json')==pre['native_probabilities_sha256']
cases=json.loads((out/'reference-cases.json').read_text(encoding='utf-8'));refs=json.loads((out/'previous-native-probabilities.json').read_text(encoding='utf-8'))
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy'];rows=[];gate_refs={}
for t in [1,2,4,8]:
    events=[json.loads(line) for line in (src/f'gate-{t}.stdout.jsonl').read_text(encoding='utf-8').splitlines()]
    for e in events[1:-1]:gate_refs[(t,e['case'])]=e['probabilities']
for path in sorted(src.glob('*.validated.json')):
    row=json.loads(path.read_text(encoding='utf-8'));t=row['threads'];job=json.loads((src/(row['run_id']+'.job.json')).read_text(encoding='utf-8'))
    raw=[json.loads(line) for line in (src/(row['run_id']+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
    assert job['cases']==cases and job['threads']==t and job['retained_f32'] is True
    validate_events(raw,cases,policy,expected_threads=t)
    init=raw[0];assert len(raw)==len(job['schedule'])+2
    assert init['retained_f32'] and (init['cached_tensors'],init['cached_bytes'])==(320,3009572096)
    assert (init['head_cached_tensors'],init['head_cached_bytes'])==(1,1044480)
    assert init['requested_threads']==init['rayon_pool_threads']==t and init['candle_env_threads']==str(t)
    assert init['expected_barrier_aux_workers']==t-1 and init['manifest_cpu_threads']==1
    for event,item in zip(raw[1:-1],job['schedule']):
        case=cases[item['case']];assert event['case']==case['id'] and event['warmup']==item['warmup'] and event['physical_tokens']==case['tokens']
        delta=max(abs(a-b) for a,b in zip(event['probabilities'],refs[event['case']]))
        assert delta<=1e-4 and (t!=1 or event['probabilities']==refs[event['case']])
        repeat=max(abs(a-b) for a,b in zip(event['probabilities'],gate_refs[(t,event['case'])]))
        assert repeat<=1e-6
        event.update(native_probability_max_abs_error=delta,repeat_probability_max_abs_error=repeat,compute_ns=event['backbone_ns']+event['head_softmax_ns'])
    assert raw==row['events'] and row['exit_code']==0 and row['guard_trigger'] is None
    if row['run_id'].startswith('resident-'):
        block=int(row['run_id'].split('-')[1]);assert job['schedule']==pre['schedules'][block]
    else:assert job['schedule']==[{'case':i,'warmup':False} for i in range(8)]
    rows.append(row)
assert pre['orders']==[[1,2,4,8],[2,8,1,4],[4,1,8,2],[8,4,2,1]]
assert all(sorted(order)==[1,2,4,8] for order in pre['orders'])
assert all(sorted(order[pos] for order in pre['orders'])==[1,2,4,8] for pos in range(4))
assert len({(a,b) for order in pre['orders'] for a,b in zip(order,order[1:])})==12
assert len(rows)==20 and sum(len(r['events'])-2 for r in rows)==112
all_events=[e for r in rows for e in r['events'][1:-1]]
numeric_by_setting={}
for t in [1,2,4,8]:
    es=[e for r in rows if r['threads']==t for e in r['events'][1:-1]]
    numeric_by_setting[str(t)]={'forwards':len(es),'exact_to_frozen_native':sum(e['probabilities']==refs[e['case']] for e in es),
        'max_native_probability_error':max(e['native_probability_max_abs_error'] for e in es),
        'max_repeat_probability_error':max(e['repeat_probability_max_abs_error'] for e in es)}
save(out/'numeric-by-setting.json',numeric_by_setting)
assert summary['processes']==20 and summary['forwards']==112 and summary['numerical_passed']
for key,event_key in [('max_onnx_probability_error','probability_max_abs_error'),('max_native_probability_error','native_probability_max_abs_error'),('max_repeat_probability_error','repeat_probability_max_abs_error')]:assert max(e[event_key] for e in all_events)==summary[key]
for t in [1,2,4,8]:
    resident=[r for r in rows if r['threads']==t and r['run_id'].startswith('resident')];es=[e for r in resident for e in r['events'][1:-1] if not e['warmup']]
    assert len(resident)==4 and len(es)==16 and all(e['physical_tokens']==e['effective_tokens']==512 for e in es)
    expected=summary['settings'][str(t)]
    for key,value in expected['stages_seconds'].items():assert stats([e[key]/1e9 for e in es])==value
    for key,value in expected['startup_stages_seconds'].items():assert stats([r['events'][0][key]/1e9 for r in resident])==value
    assert stats([r['peak_working_set_bytes'] for r in resident])==expected['peak_working_set_bytes']
    for case in cases[4:]:
        items=[e for e in es if e['case']==case['id']];assert len(items)==4
        assert stats([e['compute_ns']/1e9 for e in items])==expected['inputs'][case['id']]
for block,entry in enumerate(summary['blocks']):
    assert entry['block']==block
    for t in [1,2,4,8]:
        row=next(r for r in rows if r['run_id']==f'resident-{block}-{t}')
        assert stats([e['compute_ns']/1e9 for e in row['events'][1:-1] if not e['warmup']])==entry['compute_seconds'][str(t)]
baseline=summary['settings']['1']['stages_seconds']['compute_ns'];eligible=[]
for t in [2,4,8]:
    candidate=summary['settings'][str(t)]['stages_seconds']['compute_ns']
    if candidate['median']<baseline['median'] and candidate['p95']<baseline['p95'] and all(b['compute_seconds'][str(t)]['median']<b['compute_seconds']['1']['median'] for b in summary['blocks']):eligible.append(t)
assert eligible==summary['eligible_next_pilot_threads']
assert summary['next_pilot_threads']==(min(eligible,key=lambda t:summary['settings'][str(t)]['stages_seconds']['compute_ns']['median']) if eligible else 1)
native=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in native if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
common=json.loads((ROOT/'docs/research/jeff-onnx-tract/common512-pilot-2026-10-11/preregistration.json').read_text(encoding='utf-8'))
for a in common['assets']:
    if a['path'].endswith('bench.exe') or 'tract-scatter-candidate' in a['path']:assert sha(ROOT/a['path'])==a['sha256']
normal=json.loads((ROOT/'docs/research/jeff-onnx-tract/codegen-profile-2026-10-10/preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/tract/target/release/bench.exe')==normal['executable_sha256']
old=json.loads((prior/'preregistration.json').read_text(encoding='utf-8'))
assert sha(ROOT/'.venv/native-text-target/release/native_retained_bench.exe')==old['text_executable_sha256']
assert sha(ROOT/'.venv/native-retained-target/release/native_retained_bench.exe')==old['full_executable_sha256']
assert sha(ROOT/'.venv/bench-native-target/release/kaze_judge_native_bench.exe')=='d981d6b51ae708fd1adad0ac81845132ba8819afddf799f5afd275b7c83292c8'
save(out/'preservation.json',{'native_baseline_files':128,'native_unchanged':127,'expected_differences':diff,'sibling_files_unchanged':21,
    'frozen_native_full473_text320_executables_unchanged':True,'normal_tract_probe_unchanged':True,'accepted_tract_executable_and_174_sources_unchanged':True,'previous_text_archive_unchanged':True})
save(out/'source-validation.json',{'generated_files_reproduced':13,'backbone_readout_weights_inventory_byte_exact_to_text320':True,'release_tests_passed':9,
    'main_restores_exactly_after_reversing_thread_module_config_event_changes':True,
    'build_clippy_fmt_passed':True,'dependency_package_versions_unchanged':True,'root_dependency_only_change':'explicit Rayon =1.12.0, already in previous lock',
    'manifest_policy_cpu_threads_unchanged':1,'runtime_api_changed':False})
save(out/'validation.json',{'processes':20,'forwards':112,'gate_forwards':32,'warmup_forwards':16,'measured_forwards':64,'all_numeric_gates_passed':True,
    'one_thread_probabilities_exact_to_frozen_native':True,'all_settings_pool_size_configuration_verified':True,'repeat_tolerance':1e-6,
    'independent_raw_record_validation_and_statistics_recomputation':True,'max_onnx_probability_error':summary['max_onnx_probability_error'],
    'max_native_probability_error':summary['max_native_probability_error'],'max_repeat_probability_error':summary['max_repeat_probability_error'],
    'eligible_next_pilot_threads':eligible,'next_pilot_threads':summary['next_pilot_threads'],'formal_slo_acceptance':False,'failures':0,'guard_triggers':0})
paths=['runtime/onnx/prepare_native_threads.py','runtime/onnx/benchmark_native_threads.py','runtime/onnx/prepare_native_retained.py','runtime/onnx/benchmark_pilot.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths]+[{'path':p,'sha256':h} for p,h in generation['sources'].items() if p not in paths])
for p in paths[:2]:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_native_threads.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Native text320 FP32 thread matrix

Isolated generated wrapper, same equations/cache, threads1/2/4/8 per process.
Both environment variables set before tokenizer/tensor initialization; global
Rayon pool explicitly built and actual size checked. GEMM setting and pool
size emitted; barrier auxiliary count is a derived expectation, not telemetry.
Manifest policy remains1; experimental job overrides compute only. DeltaNet
recurrence unchanged/serial. Existing runtime/API/executables are preserved.
Thirteen generated files reproduced, nine Rust tests, release clippy/fmt pass.
Existing locked Rayon made explicit; no dependency package version change.
Four goldens + four common512 artificial requests gate each setting. Balanced
four-block Williams order; one warmup + four measured/session, n=16/setting,
per-input n=4. Twenty processes, 112 forwards = gate32 + warmup16 + measured64.
ONNX and frozen Native tolerance1e-4; one-thread frozen probabilities exact;
within-setting repeat tolerance1e-6. Judgment/tokens gates pass throughout.
Raw/schedule/cache/pool/resource records and statistics independently checked.
Next pilot candidate only: all block medians and pooled median/p95 below1,
then lowest eligible pooled median. No formal SLO/backend/API/Tract adoption.
Nearest-rank p95 at n=16 is max. Four blocks/one warmup/synthetic content,
uncontrolled thermals/affinity/background/storage cache, no quality labels.
Lifetime peak/startup n=4 incidental, not cold/private warm/API E2E evidence.
Pool size does not imply all workers active or cap total process OS threads.
No concurrent builds/tests/hash audits during timing. Previous Native/Tract
and sibling KazeNhanh remain unchanged. Distribution/NOTICE audit still open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'validation':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':summary},indent=2))
