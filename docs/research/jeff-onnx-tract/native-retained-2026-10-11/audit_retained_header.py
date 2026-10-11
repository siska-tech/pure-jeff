import json,math,pathlib,struct,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT,save,sha
manifest=json.loads((ROOT/'models/jeff-rust-bundle-p3.json').read_text(encoding='utf-8'))
path=ROOT/'models'/manifest['checkpoint_dir']/'model.safetensors'
with path.open('rb') as stream:
    length=struct.unpack('<Q',stream.read(8))[0]
    header=json.loads(stream.read(length))
tensors={k:v for k,v in header.items() if k!='__metadata__'}
used={'language_model.embed_tokens.weight','language_model.norm.weight'}
for i in range(24):
    prefix=f'language_model.layers.{i}.'
    used.update(prefix+n for n in ['input_layernorm.weight','post_attention_layernorm.weight','mlp.gate_proj.weight','mlp.up_proj.weight','mlp.down_proj.weight'])
    if i%4==3:
        used.update(prefix+'self_attn.'+n+'.weight' for n in ['q_proj','k_proj','v_proj','o_proj','q_norm','k_norm'])
    else:
        used.update(prefix+'linear_attn.'+n for n in ['in_proj_qkv.weight','conv1d.weight','in_proj_z.weight','in_proj_b.weight','in_proj_a.weight','dt_bias','A_log','norm.weight','out_proj.weight'])
assert used<=tensors.keys()
unused=set(tensors)-used
groups={}
for name,item in tensors.items():
    group=name.split('.')[0]
    row=groups.setdefault(group,{'tensors':0,'fp32_bytes':0,'file_tensor_bytes':0})
    row['tensors']+=1;row['fp32_bytes']+=math.prod(item['shape'])*4
    row['file_tensor_bytes']+=item['data_offsets'][1]-item['data_offsets'][0]
fp32=lambda names:sum(math.prod(tensors[n]['shape'])*4 for n in names)
assert len(tensors)==473 and len(used)==320 and len(unused)==153
assert all(name.startswith('visual.') for name in unused)
gate=[json.loads(line) for line in (ROOT/'experiments/runs/native-retained-20261011/gate-retained.stdout.jsonl').read_text(encoding='utf-8').splitlines()]
assert gate[0]['cached_tensors']==len(tensors) and gate[0]['cached_bytes']==fp32(tensors)
result={'method':'static inventory derived from pinned backbone 24 layers and weight names; not a timed forward profile',
    'backbone_sha256':sha(ROOT/'runtime/rust/src/backbone.rs'),'checkpoint_sha256':next(a['sha256'] for a in manifest['files'] if a['path']=='model.safetensors'),
    'all_tensors':len(tensors),'all_fp32_bytes':fp32(tensors),'used_text_tensors':len(used),'used_text_fp32_bytes':fp32(used),
    'unused_visual_tensors':len(unused),'unused_visual_fp32_bytes':fp32(unused),'namespace_inventory':groups,
    'used_names':sorted(used),'unused_names':sorted(unused),
    'scope':'accepted experiment retained all checkpoint tensors; future text-only filter unmeasured, not applied to this executable'}
save(ROOT/'experiments/runs/native-retained-20261011/weight-inventory.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ['used_names','unused_names']},indent=2))
