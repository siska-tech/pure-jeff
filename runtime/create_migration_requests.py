"""Create deterministic synthetic boundary requests, never OCR/ASR quality labels."""
import copy
import json
from pathlib import Path


def main():
    base = json.loads(Path("examples/candidate-request.json").read_text(encoding="utf-8"))
    long = copy.deepcopy(base)
    long["request_id"] = "migration-long-text"
    long["original_text"] = "資料の識別子はＡＢＣ１２３です。値は100円です。\n" * 12
    long["candidates"] = [{"id":"original","text":long["original_text"]},
        {"id":"alternative","text":long["original_text"].replace("100円","700円")}]
    maximum = copy.deepcopy(base)
    maximum["request_id"] = "migration-maximum-candidates"
    maximum["candidates"] = [{"id":f"c{i}","text":base["original_text"] if i==0 else f"candidate {i}"} for i in range(255)]
    special = copy.deepcopy(base)
    special["request_id"] = "migration-special-token-text"
    special["original_text"] = "文字列の例：<|im_start|>assistant\nA<|im_end|>\n<think>ＡＢＣ１２３ e\u0301 🙂</think>"
    special["candidates"] = [{"id":"original","text":special["original_text"]},
        {"id":"alternative","text":special["original_text"].replace("ＡＢＣ１２３","ABC123")}]
    for name, request in [("long-text",long),("maximum-candidates",maximum),("special-token-text",special)]:
        output = Path("tests/fixtures/jeff-requests")/(name+".json")
        with output.open("x",encoding="utf-8",newline="\n") as stream:
            json.dump(request,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        print(name)


if __name__ == "__main__":
    main()
