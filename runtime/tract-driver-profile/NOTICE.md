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

The separate `prepare_duplicate_experiment.py` generator restores the original
core and benchmark sources, removes all diagnostic timers, and optionally
deletes only the duplicate-search loop in `ModelPatch::apply`. Its generation
manifest identifies this as an algorithm change and records the removed text.
This experimental variant retains the upstream licenses and the existing data
patch. It is not a modification of the normal probe or a published Tract fix.
`patch_semantics.rs` is project-authored development regression code.

`prepare_name_experiment.py` creates another independent variant on top of the
duplicate-search experiment. It replaces only `Graph::unique_name` suffix
selection with the project-authored `name_index.rs`, preserving the original
prefix check and decimal naming rules. The generated manifest records the old
body and all source hashes. `name_semantics.rs` checks actual Graph and patch
behavior; this remains an experimental local change, with no upstream posting.

`prepare_forward_experiment.py` uses the accepted duplicate-removal base and
enables the pinned tract-linalg `multithread-mm` feature. Project-authored
`forward_profile.rs` wraps the public top-level eval callback, disabled by
default. Child-plan times are included in the parent operator. No suffix-index
change or internal optimizer timer is included. The separate
`forward.Cargo.lock` fixes the additional Rayon and Crossbeam dependencies:
rayon 1.12.0 and rayon-core 1.13.0 (MIT OR Apache-2.0), crossbeam-deque 0.8.8,
crossbeam-epoch 0.9.21 and crossbeam-utils 0.8.23 (MIT OR Apache-2.0).
Their crate license texts, manifest declarations and registry checksums are
archived with the forward pilot. The earlier no-new-package statement applies
to the driver/duplicate/name variants, not this optional multithread variant.
