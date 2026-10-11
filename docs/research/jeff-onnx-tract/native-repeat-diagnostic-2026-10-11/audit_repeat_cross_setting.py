import json,pathlib,shutil,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha
d=ROOT/'docs/research/jeff-onnx-tract/native-repeat-diagnostic-2026-10-11'
for item in json.loads((d/'file-index.json').read_text(encoding='utf-8')):assert sha(d/item['path'])==item['sha256']
failed=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
old=[json.loads(line) for line in (failed/'resident-1-native4.stdout.jsonl').read_text(encoding='utf-8').splitlines()][1:-1]
events=[e for path in sorted(d.glob('diagnostic-*.stdout.jsonl')) for e in [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()][1:-1]]
assert len(events)==60
result={}
for name in sorted({e['case'] for e in events}):
    probs=[e['probabilities'] for e in events if e['case']==name]
    previous=[e['probabilities'] for e in old if e['case']==name]
    assert len(probs)==12 and previous
    span=max(max(p[i] for p in probs)-min(p[i] for p in probs) for i in range(len(probs[0])))
    result[name]={'observations':12,'across_both_settings_max_span':span,
        'all_twelve_exact':all(p==probs[0] for p in probs),
        'exact_to_failed_session_observations':all(p==q for p in probs for q in previous)}
assert all(v['all_twelve_exact'] and v['exact_to_failed_session_observations'] for v in result.values())
save(d/'cross-setting-audit.json',{'cases':result,'all_twelve_exact_per_case':True,'all_match_failed_session':True,
    'failed_raw_sha256':sha(failed/'resident-1-native4.stdout.jsonl'),'causal_attribution':False,'global_28_case_reacceptance':False})
shutil.copyfile(__file__,d/'audit_repeat_cross_setting.py')
save(d/'file-index.json',[{'path':p.relative_to(d).as_posix(),'sha256':sha(p)} for p in sorted(d.rglob('*')) if p.is_file() and p.name!='file-index.json'])
print(json.dumps(result,indent=2))
