import difflib,sys
sys.path.insert(0,'runtime/onnx')
from benchmark_pilot import ROOT
from prepare_native_retained import replace_once
p=ROOT/'runtime/onnx/benchmark_length_compare.py';original=p.read_text(encoding='utf-8');text=original
text=replace_once(text,'using frozen executables.','using the numerically accepted cache-fixed Native exe.')
text=replace_once(text,'import random\n','import random\nfrom diagnose_native_repeats import host_state\n')
text=replace_once(text,"    prior = ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'", """    accepted = ROOT/'docs/research/jeff-onnx-tract/native-cache-timing-gate-2026-10-11'
    for item in json.loads((accepted/'file-index.json').read_text(encoding='utf-8')):
        if sha(accepted/item['path']) != item['sha256']:
            raise ValueError('cache-fixed numeric evidence changed')
    numeric = json.loads((accepted/'summary.json').read_text(encoding='utf-8'))
    if not numeric['all_numeric_resource_gates_passed'] or numeric['forwards'] != 84:
        raise ValueError('full28 timing-wrapper numeric acceptance required')
    native_pre = json.loads((accepted/'preregistration.json').read_text(encoding='utf-8'))
    cache_configuration = native_pre['configuration']
    previous_gate = json.loads((accepted/'old-gate-reference.json').read_text(encoding='utf-8'))
    prior = ROOT/'docs/research/jeff-onnx-tract/native-threads-2026-10-11'""")
text=replace_once(text,"native = ROOT/'.venv/native-threads-target/release/native_retained_bench.exe'","native = ROOT/'.venv/native-cache-fixed-target/release/native_cache_fixed_bench.exe'")
text=replace_once(text,"ng = ROOT/'.venv/native-threads-candidate/generation.json'","ng = ROOT/'.venv/native-cache-fixed-candidate/generation.json'")
text=replace_once(text,"(native, old['executable_sha256'])","(native, native_pre['executable_sha256'])")
text=replace_once(text,"(ng, old['generation_sha256'])","(ng, native_pre['generation_sha256'])")
text=text.replace('3561113','7901113')
text=replace_once(text,"        'previous_native_preregistration_sha256': sha(prior/'preregistration.json'),", """        'previous_native_preregistration_sha256': sha(prior/'preregistration.json'),
        'cache_fixed_acceptance_index_sha256': sha(accepted/'file-index.json'),
        'cache_configuration': cache_configuration, 'host_before': host_state(),
        'host_helper_sha256': sha(ROOT/'runtime/onnx/diagnose_native_repeats.py'),""")
text=replace_once(text,"            'profile_codegen': False, 'profile_forward': False, 'cases': cases, 'schedule': schedule})", "            'profile_codegen': False, 'profile_forward': False, 'cache_init_cpu': cache_configuration['requested_cpu'], 'cases': cases, 'schedule': schedule})")
text=replace_once(text,"        row = invoke([exe.resolve(), asset.resolve(), job.resolve()], args.output, run_id, limit)","        before = host_state()\n        if before['power_status_raw']['ac_line_status'] != 1 or before['power_status_raw']['system_status_flag'] != 0:\n            raise ValueError('AC connected and battery saver off required')\n        row = invoke([exe.resolve(), asset.resolve(), job.resolve()], args.output, run_id, limit)\n        after = host_state()\n        if after['power_status_raw']['ac_line_status'] != 1 or after['power_status_raw']['system_status_flag'] != 0:\n            raise ValueError('power condition changed')")
text=replace_once(text,"        if is_native:\n            if (init", "        if is_native:\n            if init['cache_diagnostic'] != cache_configuration:\n                raise ValueError('fixed cache/affinity metadata mismatch')\n            if (init")
text=replace_once(text,"                if gate:\n                    gate_refs", "                old_gate_error = max(abs(a-b) for a,b in zip(event['probabilities'], previous_gate[event['case']]))\n                if old_gate_error > 1e-6:\n                    raise ValueError('old Native gate mismatch')\n                event['old_gate_probability_error'] = old_gate_error\n                if gate:\n                    gate_refs")
text=replace_once(text,"        row.update(configuration=configuration, events=events)","        row.update(configuration=configuration, events=events, host_before=before, host_after=after)")
text=replace_once(text,"Native per-case repeat<=1e-6; Tract raw", "Native old gate and per-case repeat<=1e-6; Tract raw")
text=replace_once(text,"'AB/BA/AB order only partially balanced; thermals/affinity/background/storage cache uncontrolled',", "'AB/BA/AB partially balanced; Native cache init fixed/restored, compute affinity/thermals/background/storage cache uncontrolled; power/system CPU snapshots only',")
text=replace_once(text,"    rows = []; gate_refs = {}", "    rows = []; gate_refs = {}\n    save(args.output/'reference-cases.json', cases)")
text=replace_once(text,"    rows = []; gate_refs = {}", "    rows = []; gate_refs = {}; history = {}")
text=replace_once(text,"                event.update(native_probability_max_abs_error=delta", "                seen = history.setdefault(event['case'], [])\n                if any(max(abs(a-b) for a,b in zip(event['probabilities'], p)) > 1e-6 for p in seen):\n                    raise ValueError('pairwise Native repeat mismatch')\n                seen.append(event['probabilities'])\n                event.update(native_probability_max_abs_error=delta")
text=replace_once(text,"Native old gate and per-case repeat<=1e-6; Tract raw", "Native old gate and pairwise per-case repeat<=1e-6; AC connected/battery saver off before and after each child; Tract raw")
text=replace_once(text,"        run(configuration, 'gate-'+configuration, gate, True)","        for chunk in range(4):\n            run(configuration, f'gate-{configuration}-{chunk}', gate[7*chunk:7*chunk+7], True)")
text=replace_once(text,"        'sessions_per_configuration': 3,", "        'gate_chunks_per_configuration': 4, 'planned_processes': 14, 'planned_forwards': 206,\n        'sessions_per_configuration': 3,")
text=replace_once(text,"if __name__ == '__main__':\n    main()", """if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
        args = parser.parse_args()
        if args.output.exists():
            save(args.output/'failure.json', {'error_type':type(error).__name__, 'error':str(error),
                'validated_runs':sorted(p.name for p in args.output.glob('*.validated.json')),
                'numeric_acceptance':False, 'performance_acceptance':False, 'host_after':host_state()})
        raise""")
(ROOT/'runtime/onnx/benchmark_cache_fixed_lengths.py').write_text(text,encoding='utf-8')
(ROOT/'.venv/cache-fixed-length-harness.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='frozen-length-compare.py',tofile='cache-fixed-lengths.py')),encoding='utf-8')
print('new comparison harness prepared')
