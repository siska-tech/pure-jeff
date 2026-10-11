"""Fail if a built artifact contains absolute host paths (drive letters, /home, /Users).

Used in CI on engine.wasm after tools/build_wasm.py, so no user name or home directory ships.

  python tools/check_no_host_paths.py <file>...
"""
import re
import sys

PATTERN = re.compile(rb"(?:[A-Za-z]:[\\/]|/home/|/Users/)[ -~]{0,60}")


def main():
    failed = False
    for path in sys.argv[1:]:
        hits = sorted(set(PATTERN.findall(open(path, "rb").read())))
        print(f"{path}: {len(hits)} host path(s)")
        for hit in hits[:5]:
            print(f"  {hit!r}")
        failed |= bool(hits)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
