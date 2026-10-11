import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import jeff_worker as worker

class Contracts(unittest.TestCase):
    def request(self):
        return {"request_id":"r", "document_id":"d", "segment_id":"s", "profile_id":"p", "source":"ocr", "original_text":"節約する", "reason":"candidate_competition", "question_id":worker.QUESTION_ID, "candidates":[{"id":"z", "text":"節約する"},{"id":"a", "text":"節税する"}]}

    def policy(self):
        return {"min_probability":0.7,"min_margin":0.1,"cpu_threads":1}

    def decision_config(self):
        return {"format_version":1, "base_model":"fixture/qwen", "revision":"a"*40,
                "codes":[f"code_{i}" for i in range(255)], "token_ids":list(range(255)),
                "temperature":1.0}

    def test_upstream_config_without_max_options(self):
        config = self.decision_config()
        self.assertEqual(worker.validate_decision_config(config), 255)
        config["prompt_layout"] = "live-last"
        self.assertEqual(worker.validate_decision_config(config), 255)

    def test_invalid_answer_vocabulary_and_config_rejected(self):
        cases = [("format_version", True), ("format_version", 2), ("revision", "main"),
                 ("temperature", True), ("temperature", float("nan")),
                 ("temperature", 0), ("prompt_layout", "unknown"),
                 ("codes", ["A"]*255), ("codes", ["A"]),
                 ("codes", [None]*255), ("token_ids", [0]*255),
                 ("token_ids", [True]+list(range(1,255))),
                 ("token_ids", [-1]+list(range(1,255)))]
        for key, value in cases:
            with self.subTest(key=key, value=str(value)[:30]):
                config = self.decision_config()
                config[key] = value
                with self.assertRaises(ValueError):worker.validate_decision_config(config)

    def bundle(self, root):
        checkpoint, source = root/"model", root/"source"
        for path in ["config.json", "decision_config.json", "readout.safetensors", "model.safetensors", "tokenizer.json", "tokenizer_config.json"]:
            p=checkpoint/path; p.parent.mkdir(parents=True,exist_ok=True);p.write_text("{}")
        for path in ["src/jeff/__init__.py", "src/jeff/model.py", "pyproject.toml", "uv.lock", "LICENSE"]:
            p=source/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("fixture")
        manifest=root/"manifest.json"
        with patch.object(worker, "verify_checkout"):
            worker.lock_bundle(checkpoint,source,"a"*40,self.policy(),manifest)
        return checkpoint,source,manifest

    def test_bundle_verification_and_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);checkpoint,source,manifest=self.bundle(root)
            self.assertEqual(worker.verify_bundle(manifest)["source_revision"],"a"*40)
            (checkpoint/"model.safetensors").write_text("changed")
            with self.assertRaises(ValueError):worker.verify_bundle(manifest)

    def test_untracked_model_and_source_files_rejected(self):
        for kind in ("model", "source"):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);checkpoint,source,manifest=self.bundle(root)
                p=checkpoint/"extra.json" if kind=="model" else source/"src/jeff/extra.py"
                p.write_text("extra")
                with self.assertRaises(ValueError):worker.verify_bundle(manifest)

    def test_worker_pin_and_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);checkpoint,source,manifest=self.bundle(root)
            with patch.object(worker, "verify_checkout"), self.assertRaises(FileExistsError):worker.lock_bundle(checkpoint,source,"a"*40,self.policy(),manifest)
            data=json.loads(manifest.read_text());data["worker_sha256"]="0"*64;manifest.write_text(json.dumps(data))
            with self.assertRaises(ValueError):worker.verify_bundle(manifest)

    def test_bytecode_cache_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);checkpoint,source,manifest=self.bundle(root)
            cache=source/"src/jeff/__pycache__";cache.mkdir()
            (cache/"model.cpython-312.pyc").write_bytes(b"stale")
            with self.assertRaises(ValueError):worker.verify_bundle(manifest)

    def test_prompt_preserves_order_and_only_text(self):
        row=worker.make_row(self.request())
        self.assertEqual(list(row["question"]["criteria"]),["z","a"])
        self.assertEqual(row["state"],"節約する")
        self.assertNotIn("images",row)

    def test_invalid_request_rejected(self):
        for field,value in [("question_id","unknown"),("reason",None),("source","image")]:
            r=self.request();r[field]=value
            with self.assertRaises(worker.Rejected):worker.make_row(r)
        r=self.request();r["candidates"][1]["id"]="z"
        with self.assertRaises(worker.Rejected):worker.make_row(r)

    def test_selection_abstention_tie_and_invalid_distribution(self):
        for probabilities,kind in [([0.8,0.2],"selected"),([0.6,0.4],"abstained"),([0.5,0.5],"abstained")]:
            result=worker.pack_observation(self.request(),probabilities,1.0,10,self.policy(),[])
            self.assertEqual(result["judgment"]["kind"],kind)
            self.assertEqual(result["forwards"],1)
        for probabilities in ([float("nan"),0.2],[0.8,0.3],[1.0],[-0.2,1.2]):
            with self.assertRaises(worker.Rejected):worker.pack_observation(self.request(),probabilities,1.0,10,self.policy(),[])

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"bad.json";path.write_text('{"id":1,"id":2}')
            with self.assertRaises(ValueError):worker.read_json(path)

    def test_backend_single_forward_and_token_preflight(self):
        for tokens, expected_calls in [(12, 1), (33, 0)]:
            calls = []
            class Probabilities:
                def __truediv__(self, scale):
                    self.scale = scale
                    return self
                def softmax(self, dim):
                    return self
                def cpu(self):
                    return self
                def tolist(self):
                    return [[0.8, 0.2]]
            class Model:
                temperature = 1.0
                def __init__(self, **kwargs):
                    self.kwargs = kwargs
                def eval(self):
                    pass
                def prepare(self, rows, max_length):
                    self.rows = rows
                    return SimpleNamespace(input_tokens=tokens)
                def __call__(self, batch):
                    calls.append(batch)
                    return Probabilities()
            manifest = {"checkpoint":"model", "source":"source", "policy":self.policy(),
                        "checkpoint_files":[], "source_files":[], "worker_sha256":"a"*64}
            wire = {"schema_version":worker.SCHEMA, "request":self.request(),
                    "max_input_tokens":32, "max_forwards":1, "timeout_ms":1000}
            fake_modules = {"torch":SimpleNamespace(inference_mode=nullcontext),
                            "jeff":SimpleNamespace(), "jeff.model":SimpleNamespace(DecisionModel=Model)}
            with patch.dict(sys.modules, fake_modules), patch.object(sys, "path", sys.path.copy()), \
                 patch.object(worker, "verify_bundle", return_value=manifest), \
                 patch.object(worker, "check_dependencies", return_value={}), \
                 patch.object(worker, "read_json", return_value=self.decision_config()):
                if tokens <= 32:
                    result = worker.infer(wire, Path("fixture"))
                    self.assertEqual(result["input_tokens"], tokens)
                    self.assertEqual(result["forwards"], 1)
                else:
                    with self.assertRaises(worker.Rejected) as caught:
                        worker.infer(wire, Path("fixture"))
                    self.assertEqual(caught.exception.failure, "budget_exceeded")
            self.assertEqual(len(calls), expected_calls)

    def test_bad_budget_stops_before_model_import(self):
        wire={"schema_version":worker.SCHEMA,"request":self.request(),"max_input_tokens":0,"max_forwards":1,"timeout_ms":1000}
        with self.assertRaises(worker.Rejected) as caught:worker.infer(wire,Path("missing"))
        self.assertEqual(caught.exception.failure,"budget_exceeded")

if __name__=="__main__":unittest.main()
