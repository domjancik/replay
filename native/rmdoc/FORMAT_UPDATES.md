# Maintaining format compatibility

`rm-rmdoc` is a reader and normalizer, not the reMarkable format specification. Its initial compatibility oracle is this repository's Python pipeline with **rmscene 0.8.0** and the repository's legacy-v5 adapter. Parser parity is separate from native renderer fidelity. Neither compatibility with every firmware release nor exact tablet typography follows from passing the current corpus.

## Version and diagnostic policy

- Dispatch the exact 43-byte page header explicitly to v5 or v6. A new file-format major version must return an unsupported-version error until implemented; do not assume its payload is v6.
- Within v6, respect each block's declared length and supported block/item version. Never guess a new point layout from its size alone.
- Retain unknown block types, unreadable blocks, trailing fields, numeric enum codes and raw payload bytes in diagnostics. Preserve complete `.content`/`.metadata` JSON through the archive metadata API. The immutable input remains the final recovery source.
- Diagnostics are not proof that omitted data is visually irrelevant. When unsupported content could change ink, geometry or ordering, the rendering consumer must reject it or identify that limitation explicitly; it must not claim a complete rendering silently.
- Keep scene compositing order distinct from inferred replay order. Preserve moves, tombstones, group relationships, anchor resolution and uncertainty when adapting new formats. A firmware upgrade is not evidence of real stroke chronology.

## Update procedure

1. Record the source change: firmware/version observations, exact upstream rmscene release or commit, upstream license, and relevant binary-layout changes. Review upstream source manually; do not automatically accept a dependency update as parser compatibility.
2. Add minimal **synthetic** binary tests for each changed field and boundary before implementation. Include truncated length/varint cases, unsupported versions and preservation of extra bytes. Do not add device-derived notebooks or PDFs to Git.
3. Update the Python reference in a separate, deliberate change if needed. Keep existing oracle outputs available, and distinguish a Rust regression from an intentional reference behavior correction.
4. Add opt-in offline comparisons for saved private fixtures under ignored paths. Record hashes, page correspondence and coverage (tools, point versions, anchors, moves/deletions, hidden layers and scrolling geometry). Saved fixture availability alone is not coverage acceptance, and tests must not require a connected tablet.
5. Compare archive inspection, decoded/normalized semantics, projected renderer inputs and replay order against Python. Explicitly document any permitted difference, such as Rust-specific diagnostic framing; never blanket-ignore geometry, channels or ordering.
6. Render both pipelines' projected inputs with identical backend/options. Compare final pixels and final-forward/static equality, including anchored pages with the same evidence-backed layout. Add browser worker checks so target-specific WASM behavior cannot bypass the native checks.
7. Run malformed-input and resource-limit tests, native Cargo tests, package verification, and the `wasm32-unknown-unknown` build. Inspect WASM imports: a standalone module must not acquire Python, host filesystem or network requirements through a transitive dependency.
8. Update the supported-version/coverage documentation and release notes. Keep rejected cases explicit. Preserve archived evidence for previous releases instead of editing raw snapshots.

## API and release versioning

Version the serialized normalization schema independently from the Rust crate version and the input `.rm` format version. Additive optional diagnostic fields may evolve compatibly; renames, type changes, ordering changes or geometry semantics require a schema version change and migration guidance. Public Rust types and functions follow Cargo semver; while the crate is `0.x`, breaking API changes require a minor release. ABI version changes must be checked by hosts before passing buffers. Pin the reference pipeline and lock binary builds; review dependency upgrades for MSRV, license and WASM import changes.

No upstream polling, scheduled automation or automatic publication is configured by this document. Crates.io publication remains a separate reviewed release action.

## Deliberate stricter behavior than the Python reference

The parsing API preserves unreadable records. The render projection rejects unreadable known geometry blocks (types 1–8 and 13) and unknown block types, with the diagnostic error `Unsupported or unreadable geometry block ...; retained in parser diagnostics`. Unreadable informational blocks 0, 9 and 10 do not by themselves block projection. Parsed supported blocks with trailing extra fields retain those bytes in diagnostics and remain usable. This prevents silently rendering only the readable subset of ink; it is an intentional safety difference from the Python reference, not a parity defect to suppress.

The archive layer supports bounded, single-disk classic ZIP directories with stored/deflated members. It independently walks every central-directory entry before the ZIP library can collapse duplicate names. ZIP64 directory/member sentinels, multidisk envelopes and self-extracting/trailing-data envelopes fail explicitly; small archives with ZIP64 size extras only in local headers remain readable. These bounds are narrower than Python's general-purpose ZIP support. The 128 MiB compressed / 512 MiB expanded / 20,000-member limits remain in effect, and member CRCs are verified during inspection.

The locked ZIP version is 2.4.2 with only `deflate-flate2`/`flate2` and a pure Rust compression backend. ZIP 9.5.0 was evaluated but its unconditional WASM randomness dependency introduced `wasm-bindgen` imports even for this read-only library. Upgrade only after the zero-import WASM check and duplicate-directory tests pass; do not trade archive validation for a smaller dependency graph.
