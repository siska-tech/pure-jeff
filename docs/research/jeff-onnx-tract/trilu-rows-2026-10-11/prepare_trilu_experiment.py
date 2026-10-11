"""Generate a single Trilu row-fill change on the frozen multithread base."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from benchmark_pilot import ROOT, save, sha
from prepare_driver_profile import REV, replace_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    subprocess.run(["git","-C",str(args.upstream),"diff","--exit-code",REV,"--","core","data","linalg","Cargo.toml"],check=True)
    subprocess.run([sys.executable,"-B",str(ROOT/"runtime/onnx/prepare_forward_experiment.py"),
        "--upstream",str(args.upstream),"--output",str(args.output)],check=True)
    output = args.output.resolve()
    path = output/"vendor/core/src/ops/array/trilu.rs"
    original = sha(path)
    text = path.read_text(encoding="utf-8")
    text = replace_once(text,'use crate::internal::*;', 'use crate::internal::*;\nmod trilu_rows;')
    text = replace_once(text,'            for coords in tract_ndarray::indices(view.shape()) {','''            if view.ndim() >= 2 {
                let rows = view.shape()[view.ndim() - 2];
                let cols = view.shape()[view.ndim() - 1];
                if let Some(slice) = view.as_slice_mut() {
                    if trilu_rows::fill(slice, rows, cols, upper, k) {
                        return Ok(());
                    }
                }
            }
            for coords in tract_ndarray::indices(view.shape()) {''')
    path.write_text(text,encoding="utf-8")
    helper = path.parent/"trilu/trilu_rows.rs"
    helper.parent.mkdir()
    shutil.copyfile(ROOT/"runtime/tract-driver-profile/trilu_rows.rs",helper)
    generation = json.loads((output/"generation.json").read_text(encoding="utf-8"))
    generation.update(generator_sha256=sha(__file__),forward_generator_sha256=sha(ROOT/"runtime/onnx/prepare_forward_experiment.py"),
        trilu_change="contiguous row fill; original indexed fallback retained",original_trilu_sha256=original,
        result_trilu_sha256=sha(path),new_dependencies=False)
    generation["files"] = [{"path":p.relative_to(output).as_posix(),"sha256":sha(p)} for p in sorted(output.rglob("*")) if p.is_file() and p.name!="generation.json"]
    save(output/"generation.json",generation)


if __name__ == "__main__":
    main()
