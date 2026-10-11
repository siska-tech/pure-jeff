# Development exporter attribution

`export_onnx.py` is an unmodified copy from Partysun/jigor, revision
`cbd9a629f1a3d9b6829399f6f88bd3363693f9bb`, path
`scripts/jeff/export_onnx.py` (Apache-2.0; see `LICENSE.jigor`).

Source: https://github.com/Partysun/jigor/blob/cbd9a629f1a3d9b6829399f6f88bd3363693f9bb/scripts/jeff/export_onnx.py

SHA-256: `a090d94903b31b167e8eec0994ac2dff41782d197c3ad626d04a960a49cffa0b`.
The fixed revision's root listing was checked: no upstream NOTICE file was present.
This file records attribution; it is not an upstream NOTICE or a distribution approval.

KazeJudge's `export_current.py` invokes only the loading wrapper and delta-rule
patch. It replaces the upstream CLI, export inputs and parity checker, requires
the frozen checkpoint and padding gate, uses fixed batch=1, and does not use the
upstream automatic CUDA switch or its looser probability tolerance.

The delta-rule implementation derives from Hugging Face Transformers reference
code (Apache-2.0), as documented in the source. It is development tooling only.

The small ONNX Slice reproduction in the implementation evidence was extracted
from `Zatsepin/jeff-qwen3.5-0.8b-onnx` revision
`e42ca8299574aed4981d711d1c29ad66674ff4b1` (Apache-2.0;
`LICENSE.public-model`). It contains no model weights. Original model:
https://huggingface.co/Zatsepin/jeff-qwen3.5-0.8b-onnx/tree/e42ca8299574aed4981d711d1c29ad66674ff4b1
