import json,pathlib,sys,tarfile,tomllib
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,sha,save
lock=ROOT/'.venv/native-threads-candidate/Cargo.lock'
package=next(p for p in tomllib.loads(lock.read_text(encoding='utf-8'))['package'] if p['name']=='gemm-common')
assert package['version']=='0.19.0'
registry=pathlib.Path('C:/Users/<user>/.cargo/registry')
source=registry/'src/index.crates.io-1949cf8c6b5b557f/gemm-common-0.19.0'
archive=registry/'cache/index.crates.io-1949cf8c6b5b557f/gemm-common-0.19.0.crate'
assert sha(archive)==package['checksum']
files=[]
with tarfile.open(archive,'r:gz') as tar:
    for name in ['src/cache.rs','src/gemm.rs','Cargo.toml']:
        data=tar.extractfile('gemm-common-0.19.0/'+name).read()
        assert data==(source/name).read_bytes()
        files.append({'path':str(source/name),'sha256':sha(source/name),'exact_to_checksum_verified_crate':True})
    meta=tomllib.loads(tar.extractfile('gemm-common-0.19.0/Cargo.toml').read().decode('utf-8'))
save(ROOT/'.venv/gemm-cache-audit.json',{'package':package,'cargo_lock_sha256':sha(lock),
    'crate_path':str(archive),'crate_sha256':sha(archive),'files':files,'license':meta['package']['license'],
    'findings':[{'file':'src/cache.rs','lines':[303,309,330],'fact':'Intel cache information read via raw_cpuid cache parameters'},
        {'file':'src/cache.rs','lines':[475,477],'fact':'std CACHE_INFO initialized once per process'},
        {'file':'src/cache.rs','lines':[530,565,566,567,568],'fact':'kernel_params uses cache information to choose auto_kc; reduction chunking can depend on these parameters'},
        {'file':'src/gemm.rs','lines':[352,354,365,502],'fact':'shape-specific small-matrix path and general kernel_params select kc; loop uses kc for depth chunks'}],
    'hypothesis':'process initialization on different CPU/cache conditions may select different GEMM reduction chunks; unproven for this run',
    'not_observed':['actual CACHE_INFO/kernel parameters used in frozen exe','core IDs/affinity/frequency/temperature',
        'first differing backbone/head operation'],'causal_attribution':False,
    'scope':'current local dependency source matches checksum-pinned registry crate; no build-time source attestation or patch'})
print('GEMM source audit PASS; hypothesis only')
