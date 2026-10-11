"""Create synthetic 8192/8193-token requests with the fixed official processor (no forward)."""
import copy
import json
import os
from pathlib import Path
import sys

import jeff_worker as worker


def main():
    manifest_path = Path("models/jeff-bundle.json")
    manifest = worker.verify_bundle(manifest_path)
    checkpoint = Path(manifest["checkpoint"])
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(Path(manifest["source"]) / "src"))
    from jeff.model import decision_messages
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(checkpoint, local_files_only=True)
    config = worker.read_json(checkpoint / "decision_config.json")
    base = worker.read_json(Path("examples/candidate-request.json"))

    def request_for(repeats, tail):
        request = copy.deepcopy(base)
        request["original_text"] += " x" * repeats
        request["candidates"][0]["text"] = request["original_text"]
        request["candidates"][1]["text"] += " y" * tail
        return request

    def count(request):
        messages = decision_messages(worker.make_row(request), config["codes"],
                                     config.get("prompt_layout", "state-first"))
        prompt = processor.apply_chat_template(messages, tokenize=False,
                                              add_generation_prompt=True, enable_thinking=False)
        return len(processor.tokenizer.encode(prompt, add_special_tokens=False))

    for target in (8192, 8193):
        low, high = 0, target
        while low < high:
            middle = (low + high + 1) // 2
            if count(request_for(middle, 0)) <= target:
                low = middle
            else:
                high = middle - 1
        tail = target - count(request_for(low, 0))
        if not 0 <= tail <= 2:
            raise ValueError("unexpected tokenizer increments")
        request = request_for(low, tail)
        if count(request) != target:
            raise ValueError("exact token target not reached")
        request["request_id"] = f"migration-token-limit-{target}"
        output = Path(f"tests/fixtures/jeff-requests/token-limit-{target}.json")
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(request, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"path": str(output), "input_tokens": target,
                          "repeated_pairs": low, "alternative_tail": tail}), flush=True)


if __name__ == "__main__":
    main()
