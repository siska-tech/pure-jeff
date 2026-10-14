"""Write every catalog input as [{"id", "max_input_tokens", "request"}] to a new JSON file, for
deciders outside this repository's Python (the crates.io consumer of tools/check_package.py).
Their outcomes are then checked with bench/check_outcomes.py.

    python -B bench/export_cases.py <new file>"""
import json
from pathlib import Path
import sys

import catalog as cat


def main():
    target = Path(sys.argv[1])
    cases = [{"id": c["id"], "max_input_tokens": cat.MAX_TOKENS, "request": c["request"]}
             for c in cat.load()["cases"]]
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(cases, stream, ensure_ascii=False)
    print(f"{len(cases)} cases")


if __name__ == "__main__":
    main()
