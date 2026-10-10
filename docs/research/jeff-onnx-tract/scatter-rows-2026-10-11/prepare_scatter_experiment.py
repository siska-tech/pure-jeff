"""Generate a guarded ScatterElements row-copy change on the accepted Trilu base."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark_pilot import ROOT, save, sha
from prepare_driver_profile import replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, '-B', str(ROOT/'runtime/onnx/prepare_trilu_experiment.py'),
        '--upstream', str(args.upstream), '--output', str(args.output)], check=True)
    output = args.output.resolve()
    path = output/'vendor/core/src/ops/array/scatter_elements.rs'
    original = sha(path)
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, 'use crate::internal::*;', 'use crate::internal::*;\nmod scatter_rows;')
    loop = '        for (mut coords, value) in updates_view.indexed_iter() {'
    if text.count(loop) != 2:
        raise ValueError('expected one overwrite and one reduction loop')
    text = text.replace(loop, '''        if indices.shape() == updates_view.shape() {
            let shape = data.shape().to_vec();
            if let (Some(dest), Some(ix), Some(src)) =
                (data.as_slice_mut(), indices.as_slice(), updates_view.as_slice())
            {
                if scatter_rows::copy(dest, &shape, ix, src, updates_view.shape(), axis) {
                    let mut tensor = data.into_tensor();
                    unsafe { tensor.set_datum_type(updates.datum_type()) };
                    return Ok(tensor.into_tvalue());
                }
            }
        }
        for (mut coords, value) in updates_view.indexed_iter() {''', 1)
    path.write_text(text, encoding='utf-8')
    helper = path.parent/'scatter_elements/scatter_rows.rs'
    helper.parent.mkdir()
    shutil.copyfile(ROOT/'runtime/tract-driver-profile/scatter_rows.rs', helper)
    generation = json.loads((output/'generation.json').read_text(encoding='utf-8'))
    generation.update(generator_sha256=sha(__file__), trilu_generator_sha256=sha(ROOT/'runtime/onnx/prepare_trilu_experiment.py'),
        scatter_change='none reduction only; contiguous uniform-index row copy; prevalidated fallback',
        original_scatter_sha256=original, result_scatter_sha256=sha(path), new_dependencies=False)
    generation['files'] = [{'path': p.relative_to(output).as_posix(), 'sha256': sha(p)}
        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'generation.json']
    save(output/'generation.json', generation)


if __name__ == '__main__':
    main()
