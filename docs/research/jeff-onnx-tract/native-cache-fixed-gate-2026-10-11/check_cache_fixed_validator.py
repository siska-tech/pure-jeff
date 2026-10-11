import copy,json,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha
from validate_native_cache_fixed import check_events
d=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
f=ROOT/'docs/research/jeff-onnx-tract/length-compare-2026-10-11'
cases=json.loads((d/'reference-cases.json').read_text(encoding='utf-8'))
events=[json.loads(line) for line in (d/'diagnostic-0-cacheB.stdout.jsonl').read_text(encoding='utf-8').splitlines()]
schedule=json.loads((d/'diagnostic-0-cacheB.job.json').read_text(encoding='utf-8'))['schedule']
config=json.loads((d/'preregistration.json').read_text(encoding='utf-8'))['configurations']['cacheB']
old=json.loads((f/'native-length-gate-probabilities.json').read_text(encoding='utf-8'))
refs=json.loads((ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11/previous-native-probabilities.json').read_text(encoding='utf-8'))
policy=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))['policy']
check_events(copy.deepcopy(events),cases,schedule,config,policy,old,refs,{})
passed=['accepted frozen cacheB events']
def reject(name,change,first=None):
    es=copy.deepcopy(events);change(es)
    try:check_events(es,cases,schedule,config,policy,old,refs,first or {})
    except ValueError as error:passed.append({'rejected':name,'error':str(error)})
    else:raise AssertionError('accepted invalid '+name)
def shift(e,value):
    e['probabilities'][0]+=value;e['probabilities'][1]-=value
reject('old gate drift 2e-6 while ONNX tolerance still holds',lambda es:shift(es[1],2e-6))
first=copy.deepcopy(events[1]);shift(first,-8e-7)
reject('cross-process drift 1.6e-6, both within old gate1e-6',lambda es:shift(es[1],8e-7),{first['case']:first})
reject('input ID changed',lambda es:es[1]['input_ids'].__setitem__(0,es[1]['input_ids'][0]+1))
reject('raw nonfinite',lambda es:es[1]['raw_logits'].__setitem__(0,float('nan')))
reject('affinity restore metadata changed',lambda es:es[0]['cache_diagnostic'].__setitem__('affinity_restored',False))
reject('event missing',lambda es:es.pop(1))
save(ROOT/'.venv/native-cache-fixed-validator-check.json',{'source_sha256':sha(ROOT/'runtime/onnx/validate_native_cache_fixed.py'),
    'previous_archive_index_sha256':sha(d/'file-index.json'),'check_script_sha256':sha(__file__),'checks':passed})
print('validator checks PASS',len(passed))
