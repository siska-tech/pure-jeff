"""Write the 127- and 129-token neighbours of the migrated 128-token input
`synthetic-ocr-ja-2-128` into bench/cases/requests/: the same request with one filler " a" fewer
or more at the end of the original text (the length fixtures grow that suffix). The token
counts are checked by both tokenizers in build_catalog.py, not assumed here. Existing files are
never overwritten."""
import json

import catalog as cat

BASE = "synthetic-ocr-ja-2-128"


def main():
    base = next(c for c in cat.read(cat.LENGTH_INPUTS)["cases"] if c["id"] == BASE)
    request = base["request"]
    assert request["original_text"].endswith(" a"), "unexpected filler"
    cat.REQUESTS.mkdir(parents=True, exist_ok=True)
    for tokens, text in ((127, request["original_text"][:-2]), (129, request["original_text"] + " a")):
        name = f"synthetic-ocr-ja-2-{tokens}"
        value = {"provenance": f"{BASE} from {cat.LENGTH_INPUTS.relative_to(cat.ROOT).as_posix()} with the "
                               f"original text's filler suffix {'shortened' if tokens < 128 else 'extended'} by one ' a'",
                 "intended_tokens": tokens,
                 "request": {**request, "request_id": name, "original_text": text}}
        with (cat.REQUESTS / f"{name}.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
            stream.write("\n")
        print(name)


if __name__ == "__main__":
    main()
