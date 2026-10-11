"""Keep only the demo's exports in a wasm module: `memory` and `demo_*`.

The engine links the Wasm probe as a library, and Rust exports every `#[no_mangle]` function of
its dependencies, so the probe's development entry points (`kj_*`) would otherwise ship. Only
the export section is rewritten; code and other sections are copied unchanged.

Usage: python strip_exports.py input.wasm output.wasm
"""
import sys

MAGIC = b"\0asm\x01\0\0\0"
EXPORT_SECTION = 7


def keep(name):
    return name == "memory" or name.startswith("demo_")


def read_uleb(data, pos):
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def uleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def parse_exports(payload):
    count, pos = read_uleb(payload, 0)
    exports = []
    for _ in range(count):
        length, pos = read_uleb(payload, pos)
        name = payload[pos:pos + length].decode("utf-8")
        pos += length
        kind = payload[pos]
        index, end = read_uleb(payload, pos + 1)
        exports.append((name, kind, payload[pos + 1:end]))
        pos = end
    if pos != len(payload):
        raise ValueError("trailing bytes in export section")
    return exports


def strip(module):
    if not module.startswith(MAGIC):
        raise ValueError("not a wasm module (version 1)")
    out = bytearray(MAGIC)
    pos, kept, removed = len(MAGIC), [], []
    while pos < len(module):
        section = module[pos]
        size, start = read_uleb(module, pos + 1)
        payload = module[start:start + size]
        pos = start + size
        if section != EXPORT_SECTION:
            out += bytes([section]) + uleb(size) + payload
            continue
        exports = parse_exports(payload)
        kept = [e for e in exports if keep(e[0])]
        removed = [e[0] for e in exports if not keep(e[0])]
        body = uleb(len(kept)) + b"".join(
            uleb(len(name.encode())) + name.encode() + bytes([kind]) + index for name, kind, index in kept)
        out += bytes([EXPORT_SECTION]) + uleb(len(body)) + body
    if pos != len(module):
        raise ValueError("truncated module")
    return bytes(out), [e[0] for e in kept], removed


def main():
    source, target = sys.argv[1:3]
    with open(source, "rb") as stream:
        stripped, kept, removed = strip(stream.read())
    if not any(name.startswith("demo_") for name in kept) or "memory" not in kept:
        raise SystemExit("expected memory and demo_* exports")
    with open(target, "xb") as stream:
        stream.write(stripped)
    print(f"kept {len(kept)} exports, removed {len(removed)}: {', '.join(removed)}")


if __name__ == "__main__":
    main()
