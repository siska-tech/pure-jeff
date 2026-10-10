# Diagnostic Tract source use

The generator copies tract-core 0.23.8 from the official Sonos Tract repository at
`9e0cfaa9b3a9251f41f74101801dc2c937b1660a` into an ignored workspace directory.
Tract is licensed under MIT OR Apache-2.0; the original core LICENSE,
LICENSE-APACHE, and LICENSE-MIT files are retained in the generated source.
The existing data crate copy and its documented I64-to-TDim patch are preserved.

Added source consists of diagnostic timers and anchored calls around existing
graph operations. The generator records original and instrumented hashes and
refuses a different revision or changed tracked upstream source. These timers
do not change optimizer decisions. This artifact is for development profiling;
it is separate from the normal Tract probe and Native runtime.

No new dependency package is introduced: the existing pinned tract-core package
is replaced only in the generated build. The generated Cargo.lock and complete
source hash index must accompany measurements. The original upstream cache is
not edited. This notice does not constitute distribution approval.
