"""Record the locked Windows dependency graph, build scripts and PE imports.

This evidence supports manual review; absence of known native crates is not proof
that arbitrary dependency source contains no FFI. No network or installs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def pe_imports(path):
    data = path.read_bytes()
    pe = struct.unpack_from("<I",data,0x3c)[0]
    if data[:2] != b"MZ" or data[pe:pe+4] != b"PE\0\0":
        raise ValueError("not a PE executable")
    sections, optional_size = struct.unpack_from("<H",data,pe+6)[0], struct.unpack_from("<H",data,pe+20)[0]
    optional = pe+24
    if struct.unpack_from("<H",data,optional)[0] != 0x20b:
        raise ValueError("expected PE32+ executable")
    section_base = optional+optional_size
    def offset(rva):
        for i in range(sections):
            virtual_size, start, size, raw = struct.unpack_from("<IIII",data,section_base+i*40+8)
            if start <= rva < start+max(virtual_size,size):
                return raw+rva-start
        raise ValueError("unmapped PE RVA")
    imports = []
    rva = struct.unpack_from("<I",data,optional+112+8)[0]
    if rva:
        cursor = offset(rva)
        while any(data[cursor:cursor+20]):
            name = offset(struct.unpack_from("<I",data,cursor+12)[0])
            imports.append(data[name:data.index(b"\0",name)].decode("ascii"))
            cursor += 20
    if struct.unpack_from("<I",data,optional+112+13*8)[0]:
        raise ValueError("delay imports require additional review")
    return sorted(set(imports),key=str.lower)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    crate = Path(__file__).resolve().parent/"rust"
    metadata = json.loads(subprocess.check_output([
        "cargo","metadata","--locked","--offline","--manifest-path",str(crate/"Cargo.toml"),
        "--filter-platform","x86_64-pc-windows-msvc","--format-version","1"],text=True,encoding="utf-8"))
    nodes = {node["id"]:node for node in metadata["resolve"]["nodes"]}
    packages = []
    for package in sorted(metadata["packages"],key=lambda p:(p["name"],p["version"])):
        if package["id"] not in nodes:
            continue
        base = Path(package["manifest_path"]).parent
        scripts = [{"path":str(Path(t["src_path"]).relative_to(base)).replace("\\","/"),
                    "sha256":sha(Path(t["src_path"]))}
                   for t in package["targets"] if "custom-build" in t["kind"]]
        packages.append({"name":package["name"],"version":package["version"],
                         "source":package["source"],"features":nodes[package["id"]]["features"],
                         "license":package["license"],"links":package["links"],"build_scripts":scripts})
    prohibited = {"cc","cmake","onig_sys","torch-sys","tch","ort","ort-sys",
                  "intel-mkl-src","accelerate-src","cudarc","candle-kernels","openssl-sys"}
    found = sorted({p["name"] for p in packages}&prohibited)
    esaxx = next(p for p in packages if p["name"]=="esaxx-rs")
    candle = next(p for p in packages if p["name"]=="candle-core")
    tokenizer = next(p for p in packages if p["name"]=="tokenizers")
    forbidden_features = {"cpp","onig","esaxx_fast","cuda","cudnn","metal","mkl","accelerate"}
    features = sorted(set(esaxx["features"]+candle["features"]+tokenizer["features"])&forbidden_features)
    if found or features:
        raise ValueError(f"native dependency review required: {found}, {features}")
    result = {"schema_version":"kaze_judge.rust_dependency_audit.v1",
              "target":"x86_64-pc-windows-msvc","cargo_lock_sha256":sha(crate/"Cargo.lock"),
              "auditor_sha256":sha(Path(__file__)),"executable_sha256":sha(args.executable),
              "executable_direct_imports":pe_imports(args.executable),
              "known_prohibited_dependencies":found,"known_prohibited_features":features,
              "esaxx_cpp_enabled":"cpp" in esaxx["features"],"packages":packages,
              "scope":"initial feature/build-script/import evidence; manual source and distribution review remains"}
    encoded = json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        stream.write(encoded)
    print(json.dumps({"packages":len(packages),"imports":result["executable_direct_imports"],"esaxx_cpp_enabled":False}))


if __name__ == "__main__":
    main()
