"""Generate a fail-closed text-only retention candidate from the accepted full cache."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess

from benchmark_pilot import ROOT, save, sha
from prepare_native_retained import replace_once


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    prior=ROOT/'docs/research/jeff-onnx-tract/native-retained-2026-10-11'
    for item in json.loads((prior/'file-index.json').read_text(encoding='utf-8')):
        if sha(prior/item['path'])!=item['sha256']:raise ValueError('full-cache evidence changed')
    inventory=json.loads((prior/'weight-inventory.json').read_text(encoding='utf-8'))
    keep=inventory['used_names'];all_names=sorted(keep+inventory['unused_names'])
    if len(keep)!=320 or len(all_names)!=473 or len(set(all_names))!=473:raise ValueError('inventory coverage changed')
    generation=json.loads((prior/'generation.json').read_text(encoding='utf-8'))
    for path,digest in generation['sources'].items():
        if sha(ROOT/path)!=digest:raise ValueError('original source changed')
    args.output.mkdir(parents=True,exist_ok=False)
    for item in generation['files']:
        source=prior/'generated'/item['path'];target=args.output/item['path']
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    weights=args.output/'src/weights.rs'
    original=weights.read_text(encoding='utf-8')
    adapted=replace_once(original,'use std::collections::BTreeMap;','''use std::collections::BTreeMap;
#[path = "text_inventory.rs"]
mod text_inventory;

fn text_weight_names(mut names: Vec<String>) -> Result<Vec<String>> {
    names.sort();
    if names == ["weight"] {
        return Ok(names); // Separate, verified Decision Head file.
    }
    if !names.iter().map(String::as_str).eq(text_inventory::ALL_NAMES.iter().copied()) {
        candle_core::bail!("checkpoint tensor inventory differs from pinned full model")
    }
    Ok(text_inventory::TEXT_NAMES.iter().map(|name| (*name).to_owned()).collect())
}''')
    adapted=replace_once(adapted,'        let mut names: Vec<_> = mapped.tensors().into_iter().map(|(name, _)| name).collect();\n        names.sort();',
        '        let names = text_weight_names(mapped.tensors().into_iter().map(|(name, _)| name).collect())?;')
    adapted+='''
#[cfg(test)]
mod selection_tests {
    use super::*;
    fn complete() -> Vec<String> {
        text_inventory::ALL_NAMES.iter().rev().map(|s| (*s).to_owned()).collect()
    }
    #[test]
    fn selects_exact_text_inventory_from_unordered_full_model() -> Result<()> {
        let selected = text_weight_names(complete())?;
        assert_eq!(selected.len(), 320);
        assert!(selected.iter().all(|s| s.starts_with("language_model.")));
        assert!(selected.iter().map(String::as_str).eq(text_inventory::TEXT_NAMES.iter().copied()));
        Ok(())
    }
    #[test]
    fn rejects_missing_duplicate_and_unexpected_model_names() {
        let mut missing = complete(); missing.pop();
        assert!(text_weight_names(missing).is_err());
        let mut duplicate = complete(); duplicate.push(duplicate[0].clone());
        assert!(text_weight_names(duplicate).is_err());
        let mut unexpected = complete(); unexpected[0] = "unexpected.weight".into();
        assert!(text_weight_names(unexpected).is_err());
    }
    #[test]
    fn preserves_head_and_rejects_ambiguous_file() -> Result<()> {
        assert_eq!(text_weight_names(vec!["weight".into()])?, vec!["weight"]);
        assert!(text_weight_names(vec!["weight".into(), "extra".into()]).is_err());
        assert!(text_weight_names(vec![]).is_err());
        Ok(())
    }
}
'''
    weights.write_text(adapted,encoding='utf-8')
    constants='//! Pinned checkpoint inventory; generated from audited Native text weight names.\n'
    for name,values in [('ALL_NAMES',all_names),('TEXT_NAMES',keep)]:
        constants+=f'pub const {name}: &[&str] = &[\n'+''.join('    '+json.dumps(v)+',\n' for v in values)+'];\n'
    (args.output/'src/text_inventory.rs').write_text(constants,encoding='utf-8')
    subprocess.run(['rustfmt','--edition','2021',str(weights),str(args.output/'src/text_inventory.rs')],check=True)
    adapted=weights.read_text(encoding='utf-8')
    (args.output/'text-selection.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),adapted.splitlines(True),fromfile='full-cache-weights',tofile='text-cache-weights',n=0)),encoding='utf-8')
    save(args.output/'generation.json',{'generator_sha256':sha(__file__),
        'anchor_helper_sha256':sha(ROOT/'runtime/onnx/prepare_native_retained.py'),
        'previous_generation_sha256':sha(prior/'generation.json'),'inventory_sha256':sha(prior/'weight-inventory.json'),
        'sources':generation['sources'],'model_tensors':320,'model_fp32_bytes':inventory['used_text_fp32_bytes'],
        'head_tensors':1,'head_fp32_bytes':1044480,'removed_tensors':153,'removed_fp32_payload_bytes':inventory['unused_visual_fp32_bytes'],
        'rustfmt_version':subprocess.check_output(['rustfmt','--version'],text=True).strip(),
        'files':[{'path':p.relative_to(args.output).as_posix(),'sha256':sha(p)} for p in sorted(args.output.rglob('*')) if p.is_file()],
        'scope':'only retained tensor selection changes; equations/wrapper/dependencies unchanged; full inventory mismatch fails'})
    print('generated text320 candidate, full inventory guard and head preserved',flush=True)


if __name__=='__main__':
    main()
