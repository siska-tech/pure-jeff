# 公開Jeff ONNXの全演算子

2026-10-10。固定graphの静的集計。実行互換性の認定ではない。

Graph SHA-256: `4e38fcec2ed74ad6daebd345d8e10bff8bd4534cf428066c1f7f8ea847072a24`。opset 18、113,333ノード、48種類。

[互換性マトリクス](../../onnx-tract-compatibility.md) / [JSON証跡](onnx-static-inventory.json)

| ONNX演算子 | 個数 | Tract 0.23.8の明示登録先 |
| --- | ---: | --- |
| Add | 551 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| And | 2 | [onnx/src/ops/logic.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/logic.rs) |
| Cast | 24,407 | [onnx/src/ops/cast.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/cast.rs) |
| CastLike | 2,617 | [onnx/src/ops/cast.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/cast.rs) |
| Concat | 3,757 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Constant | 34,258 | [onnx/src/ops/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/mod.rs) |
| Conv | 18 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| Cos | 1 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| CumSum | 18 | [onnx/src/ops/cumsum.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/cumsum.rs) |
| Div | 18 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Equal | 18 | [onnx/src/ops/logic.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/logic.rs) |
| Exp | 108 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Expand | 2,542 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Gather | 1,154 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| GatherND | 1 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Gemm | 1 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Greater | 18 | [onnx/src/ops/logic.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/logic.rs) |
| Identity | 42 | [onnx/src/ops/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/mod.rs) |
| IsNaN | 6 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| LessOrEqual | 1 | [onnx/src/ops/logic.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/logic.rs) |
| MatMul | 3,097 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Max | 1 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Mul | 702 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Neg | 1,164 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Pad | 90 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Pow | 79 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Range | 188 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Reciprocal | 115 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| ReduceMean | 79 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| ReduceSum | 36 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| Reshape | 24,931 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| ScatterElements | 148 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| ScatterND | 148 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| SequenceAt | 66 | **登録なし** |
| Shape | 2,626 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Sigmoid | 84 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| Sin | 1 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Slice | 8,250 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Softmax | 6 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| Softplus | 18 | [onnx/src/ops/nn/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/nn/mod.rs) |
| SplitToSequence | 24 | **登録なし** |
| Sqrt | 127 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Squeeze | 19 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Sub | 180 | [onnx/src/ops/math.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/math.rs) |
| Transpose | 537 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Trilu | 36 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Unsqueeze | 995 | [onnx/src/ops/array/mod.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/array/mod.rs) |
| Where | 48 | [onnx/src/ops/logic.rs](https://github.com/sonos/tract/blob/9e0cfaa9b3a9251f41f74101801dc2c937b1660a/onnx/src/ops/logic.rs) |

登録あり46種類もdtype・shape・attributes・opsetの実条件での試験が必要。
未登録2種類は出力へ到達するため、不要ノードとして削除するだけでは解決しない。
