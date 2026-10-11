import json,pathlib,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import save,sha
from observe_windows_host import invoke_observed
out=pathlib.Path('experiments/runs/host-observer-20261011')
save(out/'wrapper-preregistration.json',{'script_sha256':sha(__file__),'observer_sha256':sha('runtime/onnx/observe_windows_host.py'),
 'cases':['success','nonzero','deadline'],'memory_limit_bytes':256*1024**2,'inference_forwards':0,
 'purpose':'child lifecycle/guard smoke only; Python development child, not model runtime'})
rows=[]
for name,code,timeout in [('success','import time; time.sleep(3)',5),('nonzero','import time; time.sleep(2); raise SystemExit(7)',5),('deadline','import time; time.sleep(3)',.3)]:
    try:
        record=invoke_observed([sys.executable,'-c',code],out,name,256*1024**2,timeout)
        assert name=='success' and record['host_observation']['sampled_conditions_passed']
        rows.append({'case':name,'expected_failure':False,'passed':True})
    except RuntimeError as error:
        assert name!='success'
        record=json.loads((out/(name+'.process.json')).read_text())
        assert record['status']=='failed'
        assert (record['exit_code']==7 and record['guard_trigger'] is None) if name=='nonzero' else record['guard_trigger']=='deadline'
        assert (out/(name+'.host-summary.json')).exists()
        rows.append({'case':name,'expected_failure':True,'passed':True,'error':str(error)})
save(out/'wrapper-validation.json',rows)
print(json.dumps(rows,indent=2))
