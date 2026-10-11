# Tract data crate and local patch

`data/` is copied from sonos/tract commit
`9e0cfaa9b3a9251f41f74101801dc2c937b1660a` (0.23.8).
Original file hashes are recorded in `upstream.json`.
The original MIT / Apache-2.0 license texts are retained alongside this notice.
The small enclosing workspace manifest reproduces this crate's dependency
declarations from that commit; the other Tract crates remain pinned Git dependencies.

KazeJudge modification: `data/src/tensor.rs`, numeric cast to `TDim`.
For an `I64` source only, preserve the original 64-bit values instead of casting
through `i32`. This prevents `INT64_MAX` ONNX Slice ends from becoming `-1`.
Other source datum types retain upstream behavior. No inference kernel is added.

The native Jeff runtime and adjacent Tract checkout do not use this patch.
This development patch has not been submitted upstream or approved for release.
