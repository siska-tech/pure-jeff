import json,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,sha,save
candidate=ROOT/'.venv/native-cache-fixed-candidate';repro=ROOT/'.venv/native-cache-fixed-reproduction'
prior=ROOT/'docs/research/jeff-onnx-tract/native-cache-diagnostic-2026-10-11'
audit=json.loads((prior/'dependency-feature-audit.json').read_text(encoding='utf-8'))
old=ROOT/'.venv/native-cache-v2-metadata.json'
assert sha(old)==audit['after_metadata_sha256']
before=json.loads(old.read_text(encoding='utf-8-sig'));after=json.loads((ROOT/'.venv/native-cache-fixed-metadata.json').read_text(encoding='utf-8-sig'))
def features(meta):return {n['id']:n['features'] for n in meta['resolve']['nodes'] if n['id']!=meta['resolve']['root']}
assert features(before)==features(after) and len(features(after))==156
files=[p for p in candidate.rglob('*') if p.is_file()]
assert all(sha(p)==sha(repro/p.relative_to(candidate)) for p in files)
unchanged=['backbone.rs','weights.rs','readout.rs','threads.rs']
assert all(sha(candidate/'src'/n)==sha(ROOT/'.venv/native-threads-candidate/src'/n) for n in unchanged)
assert sha(candidate/'src/cache_diagnostic.rs')==sha(prior/'generated-source/src/cache_diagnostic.rs')
save(ROOT/'.venv/native-cache-fixed-source-audit.json',{'dependency_packages_features_identical':156,
    'generated_files_identical':len(files),'unchanged_compute_source':unchanged,
    'cache_module_identical_to_diagnostic':True,'before_metadata_sha256':sha(old),
    'after_metadata_sha256':sha(ROOT/'.venv/native-cache-fixed-metadata.json'),'features':features(after),
    'generator_sha256':sha(ROOT/'runtime/onnx/prepare_native_cache_fixed.py'),
    'generation_sha256':sha(candidate/'generation.json')})
print('source/feature audit PASS',len(files))
