import hashlib,json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha,validate_events
src=ROOT/'experiments/runs/native-repeat-diagnostic-20261011'
out=ROOT/'docs/research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11'
failure=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
pre=json.loads((src/'preregistration.json').read_text(encoding='utf-8'))
s=json.loads((src/'summary.json').read_text(encoding='utf-8'))
assert sha(ROOT/'runtime/onnx/diagnose_native_repeats.py')==pre['script_sha256']
assert sha(ROOT/'runtime/onnx/benchmark_pilot.py')==pre['helper_sha256']
for item in json.loads((failure/'file-index.json').read_text(encoding='utf-8')):assert sha(failure/item['path'])==item['sha256']
for asset in pre['assets']:assert sha(ROOT/asset['path'])==asset['sha256']
assert sha(failure/'preregistration.json')==pre['failure_preregistration_sha256']
assert sha(failure/'reference-cases.json')==pre['failure_reference_cases_sha256']
assert sha(failure/'repeat-violations.json')==pre['failure_violations_sha256']
assert sha(failure/'native-length-gate-probabilities.json')==pre['old_gate_sha256']
ids=sorted({v['case'] for v in json.loads((failure/'repeat-violations.json').read_text(encoding='utf-8'))})+['synthetic-asr-unicode-2-512']
assert ids==pre['case_ids'] and pre['orders']==[[1,4],[4,1]] and pre['planned_forwards']==60 and pre['repeat_threshold']==1e-6
all_cases=json.loads((failure/'reference-cases.json').read_text(encoding='utf-8'))
cases=[next(case for case in all_cases if case['id']==name) for name in ids]
old=json.loads((failure/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
rows=[];host=[]
for block,order in enumerate(pre['orders']):
    for t in order:
        run_id=f'diagnostic-{block}-threads{t}'
        job=json.loads((src/(run_id+'.job.json')).read_text(encoding='utf-8'))
        record=json.loads((src/(run_id+'.process.json')).read_text(encoding='utf-8'))
        row=json.loads((src/(run_id+'.validated.json')).read_text(encoding='utf-8'))
        events=[json.loads(line) for line in (src/(run_id+'.stdout.jsonl')).read_text(encoding='utf-8').splitlines()]
        assert job['cases']==cases and job['schedule']==pre['schedules'][block] and job['threads']==t and job['retained_f32']
        assert all(sum(i['case']==case for i in job['schedule'])==3 for case in range(5))
        assert len(events)==17;validate_events(events,cases,policy,expected_threads=t);init=events[0]
        assert init['requested_threads']==init['rayon_pool_threads']==t and init['candle_env_threads']==str(t)
        assert init['expected_barrier_aux_workers']==t-1 and init['manifest_cpu_threads']==1 and init['retained_f32']
        assert (init['cached_tensors'],init['cached_bytes'],init['head_cached_tensors'],init['head_cached_bytes'])==(320,3009572096,1,1044480)
        for e,item in zip(events[1:-1],job['schedule']):
            assert e['case']==cases[item['case']]['id'] and not e['warmup'] and e['physical_tokens']==e['effective_tokens']
            e['old_native4_gate_error']=max(abs(a-b) for a,b in zip(e['probabilities'],old[e['case']]))
        assert events==row['events'] and row['threads']==t and row['block']==block
        assert all(row[k]==v for k,v in record.items())
        assert record['exit_code']==0 and record['guard_trigger'] is None and record['status']=='completed'
        assert record['timeout_seconds']==600 and record['parent_process_ns']<=600*10**9 and record['memory_samples']>0
        assert 0<record['peak_working_set_bytes']<=record['memory_limit_bytes']==pre['memory_limit_bytes']
        assert record['command']==[str((ROOT/'.venv/native-threads-target/release/native_retained_bench.exe').resolve()),
            str((ROOT/'models/jeff-rust-bundle-p3.json').resolve()),str((src/(run_id+'.job.json')).resolve())]
        a=row['host_before']['system_cpu_100ns'];b=row['host_after']['system_cpu_100ns']
        total=b['kernel_including_idle']+b['user']-a['kernel_including_idle']-a['user']
        busy=100*(total-b['idle']+a['idle'])/total
        assert abs(busy-row['system_wide_average_busy_percent'])<1e-12 and 0<=busy<=100
        host.append({'run_id':run_id,'system_wide_average_busy_percent':busy,
            'before_power':row['host_before']['power_status_raw'],'after_power':row['host_after']['power_status_raw']})
        rows.append(row)
assert len(rows)==4 and s['observed_forwards']==60
assert s['max_onnx_error']==max(e['probability_max_abs_error'] for row in rows for e in row['events'][1:-1])
def span(values):
    return max(max(p[i] for p in values)-min(p[i] for p in values) for i in range(len(values[0])))
for t in [1,4]:
    selected=[r for r in rows if r['threads']==t]
    for case in cases:
        groups=[[e['probabilities'] for e in row['events'][1:-1] if e['case']==case['id']] for row in selected]
        assert len(groups)==2 and all(len(group)==3 for group in groups)
        probs=groups[0]+groups[1]
        expected={'tokens':case['tokens'],'within_process_max_span':max(span(g) for g in groups),
            'between_process_first_error':max(abs(a-b) for a,b in zip(groups[0][0],groups[1][0])),
            'all_six_max_span':span(probs),'all_six_exact':all(p==probs[0] for p in probs),
            'max_old_native4_gate_error':max(abs(a-b) for p in probs for a,b in zip(p,old[case['id']]))}
        assert expected==s['threads'][str(t)]['cases'][case['id']]
    v=s['threads'][str(t)]
    assert v['subset_span_within_1e6']==all(c['all_six_max_span']<=1e-6 for c in v['cases'].values())
    assert v['subset_old_gate_within_1e6']==all(c['max_old_native4_gate_error']<=1e-6 for c in v['cases'].values())
assert s['all_onnx_probability_judgment_token_gates_passed'] and not s['global_28_case_reacceptance'] and not s['performance_acceptance'] and not s['formal_slo_acceptance']
baseline=json.loads((ROOT/'experiments/runs/native-baseline-20261010/archive-index.json').read_text(encoding='utf-8'))['files']
diff=[a['path'] for a in baseline if sha(ROOT/a['path'])!=a['sha256']];assert diff==['.gitignore']
sibling=json.loads((ROOT/'docs/research/jeff-onnx-tract/implementation-2026-10-10/sibling-core-index.json').read_text(encoding='utf-8'))['files']
assert all(sha(ROOT.parent/'KazeNhanh'/a['path'])==a['sha256'] for a in sibling)
out.mkdir(parents=True,exist_ok=False)
for p in src.iterdir():
    if p.is_file():shutil.copyfile(p,out/p.name)
for n in ['LICENSE','LICENSE-APACHE','LICENSE-MIT','NOTICE.md']:shutil.copyfile(failure/n,out/n)
audit=json.loads((ROOT/'.venv/gemm-cache-audit.json').read_text(encoding='utf-8'))
assert sha(audit['crate_path'])==audit['crate_sha256']==audit['package']['checksum']
assert sha(ROOT/'.venv/native-threads-candidate/Cargo.lock')==audit['cargo_lock_sha256']
for item in audit['files']:assert sha(item['path'])==item['sha256']
shutil.copyfile(ROOT/'.venv/gemm-cache-audit.json',out/'gemm-cache-audit.json')
shutil.copyfile(ROOT/'.venv/audit_gemm_cache.py',out/'audit_gemm_cache.py')
save(out/'reference-cases.json',cases);save(out/'previous-native4-gate.json',{name:old[name] for name in ids})
save(out/'host-observations.json',host)
save(out/'validation.json',{'independent_raw_schedule_pool_cache_resource_probability_span_and_cpu_delta_audit':True,
    'processes':4,'forwards':60,'all_onnx_probability_judgment_token_gates_passed':True,
    'native_baseline_unchanged':127,'known_gitignore_difference_only':True,'sibling_files_unchanged':21,
    'failed_length_archive_and_frozen_assets_unchanged':True,'performance_acceptance':False,'global_28_case_reacceptance':False,'formal_slo_acceptance':False})
paths=['runtime/onnx/diagnose_native_repeats.py','runtime/onnx/benchmark_pilot.py']
save(out/'source-index.json',[{'path':p,'sha256':sha(ROOT/p)} for p in paths])
for p in paths:shutil.copyfile(ROOT/p,out/pathlib.Path(p).name)
shutil.copyfile(__file__,out/'archive_repeat_diagnostic.py')
normalizations=[]
for p in out.glob('*.log'):
    original=p.read_bytes();normalized=b'\n'.join(line.rstrip(b' \t\r') for line in original.rstrip(b'\r\n').split(b'\n'))+b'\n' if original else b''
    p.write_bytes(normalized)
    if original!=normalized:normalizations.append({'path':p.name,'original_sha256':hashlib.sha256(original).hexdigest(),'change':'strip trailing whitespace/CRLF; ignored original retained'})
save(out/'log-archival.json',normalizations)
(out/'README.md').write_text('''# Native numerical repeat diagnosis, not performance reacceptance

Frozen text320/head1 FP32 exe, step1113, batch1, native effective length.
Four failed cases128/384/511 plus one unicode512 control. Threads1/4,
two sessions each, AB/BA order, three repeats/case/session = four processes/
60 forwards. No warmup or latency acceptance; raw times are diagnostics only.
ONNX probability1e-4/sum1e-6/judgment/token/resource gates stop on failure;
registered fixed60 collected regardless of repeat1e-6 exceedances, which
remain recorded, never relabeled as a successful performance comparison.
Within-process span, cross-process first delta, six-observation span and
old failed-run Native4 gate differences independently recomputed. JSON keys
ending within_1e6 mean within registered1e-6, as comparison code/preregistration
specify. Native raw/hidden logits not instrumented; causal source unknown.
Power raw and system CPU cumulative snapshots before/after each child;
average busy percent includes unrelated processes, not child utilization or
contention proof. No affinity/frequency/temperature/active worker telemetry.
Same artificial inputs, two sessions, no 28-case reacceptance, formal SLO,
backend adoption or recognition-quality claim. Previous failed run and
frozen assets, Native/API and sibling preserved. Distribution NOTICE open.
''',encoding='utf-8')
save(out/'file-index.json',[{'path':p.relative_to(out).as_posix(),'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps({'audit':'PASS','indexed_files':len(json.loads((out/'file-index.json').read_text(encoding='utf-8'))),'summary':s,'host':host},indent=2))
