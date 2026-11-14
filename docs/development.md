# Development

## Hosted app

The reader, renderer and replay core are independent Cargo packages:

```sh
rustup target add wasm32-unknown-unknown
cargo build --locked --release --target wasm32-unknown-unknown --manifest-path native/rmdoc/Cargo.toml
cargo build --locked --release --target wasm32-unknown-unknown --manifest-path native/redraw/Cargo.toml
cargo build --locked --release --target wasm32-unknown-unknown --manifest-path native/replay-core/Cargo.toml
```

Build the encoder using [its guide](../native/video-prototype/README.md), then stage the app:

```sh
uv sync --locked --all-groups
uv run --locked python scripts/fetch-site-examples.py
uv run --locked python native/hosted/build.py
node --test tests/web/*.test.mjs tests/hosted/*.test.mjs
uv run --locked pytest tests/hosted
```

Output: `artifacts/hosted-replay`, containing generated Vercel configuration and public assets. Browser users do not need Python; the current staging tool does.

## Renderer release checks

```sh
cargo test --locked --manifest-path native/redraw/Cargo.toml
cargo package --locked --manifest-path native/redraw/Cargo.toml --list
cargo publish --dry-run --locked --manifest-path native/redraw/Cargo.toml
```

Run from a clean checkout, review package contents and licenses. Dry runs do not reserve a name or establish registry ownership. Actual publication is a separate maintainer action.

See [parity instructions](rust-renderer.md) for native/WASM comparison with Python. Keep generated outputs and device captures under ignored paths.

The public landing page is `/`; the workspace is `/app`. Both share the same origin and browser storage. Approved demonstration media are downloaded from the `site-examples-v1` GitHub release and checked against `native/hosted/examples.json`; generated videos/images stay out of Git history.
