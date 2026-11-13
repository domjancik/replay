# Third-party components

rm-redraw uses independently distributed Python packages. They retain their own copyright and license terms. The source/wheel release does not vendor their source or binaries; installing dependencies obtains separate distributions with their notices. Preserve those notices when redistributing an installed environment or bundled application.

The versions below describe the locked environment inspected for this preview. See `uv.lock` for the complete dependency graph, environment markers and hashes. License labels were inspected in installed distribution metadata; packages can contain components under additional terms, so their complete notices remain authoritative.

| Runtime component | Locked version | Declared license / notices | Upstream |
| --- | --- | --- | --- |
| rmscene | 0.8.0 | MIT | https://github.com/ricklupton/rmscene |
| NumPy | 2.5.2 | BSD-3-Clause; bundled-component terms also include 0BSD, MIT, Zlib and CC0 | https://numpy.org/ |
| Pillow | 12.3.0 | MIT-CMU; binary codec notices also apply | https://python-pillow.github.io/ |
| pypdf | 6.17.0 | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| SciPy | 1.18.1 | BSD-3-Clause and bundled-component notices | https://scipy.org/ |
| scikit-image | 0.26.0 | BSD-3-Clause and per-file notices | https://scikit-image.org/ |
| ImageIO | 2.37.4 | BSD-2-Clause | https://imageio.readthedocs.io/ |
| tifffile | 2026.8.23 | BSD-3-Clause | https://github.com/cgohlke/tifffile |
| NetworkX | 3.6.1 | BSD-3-Clause | https://networkx.org/ |
| lazy-loader | 0.5 | BSD-3-Clause | https://github.com/scientific-python/lazy-loader |
| packaging | 23.2 | Apache-2.0 or BSD-2-Clause; see distribution LICENSE | https://github.com/pypa/packaging |

## External tools

FFmpeg/ffprobe and Poppler/pdftoppm are separate executables installed by the user. They are not bundled. FFmpeg licensing depends on build configuration; the tested video path uses libx264. Any future bundled installer must review the exact binaries and include their required source/notice obligations. This preview does not make a blanket claim about distributing arbitrary third-party binary builds.

The optional cloud import preview uses user-installed rmctl or rmctl-lite v1.2.0. The rmctl project is MIT-licensed. Its release archives may have additional notices for bundled components. The optional stdin pairing patch contains MIT-licensed upstream context, with its notice in `native/rmctl-pairing/LICENSE`. The rm-redraw distribution excludes generated rmctl and pairing companion executables. [rmctl v1.2.0 license](https://github.com/altessa-s/rmctl/blob/v1.2.0/LICENSE) · [Upstream release](https://github.com/altessa-s/rmctl/releases/tag/v1.2.0)

The optional Rust pencil kernel and research WASM wrapper have no third-party Cargo dependencies. Rust and Node are external toolchains for building and running the probe. The Python package does not bundle their executables or generated WASM.

The separate browser video probe builds against Mediabunny 1.65.2 (MPL-2.0), using esbuild 0.28.2 (MIT) as a build tool. Its generated bundle stays outside the Python distribution. A future redistributed bundle should preserve the Mediabunny notice and provide its corresponding source under MPL-2.0. [Mediabunny license](https://github.com/Vanilagy/mediabunny/blob/v1.65.2/LICENSE) · [esbuild license](https://github.com/evanw/esbuild/blob/v0.28.2/LICENSE.md) · [Mozilla MPL distribution guidance](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)

## References versus dependencies

The calibration article discusses other open-source renderers and brush engines. Merely listing a project as a research reference does not make it a dependency. In particular, `rmc`, `librm_lines`, Quill, RMRender and inkterop are not runtime requirements of this package. Claims and license descriptions for those references are separately sourced in `docs/renderer-landscape.md`.

## Project and artwork terms

The project code and documentation are MIT-licensed; see LICENSE. Selected artwork requires separate owner review before publication. Existing tablet documents, reference exports and visual comparison artifacts are not included in the package. They are not covered by any future code license merely because they were used for local testing. The private visual annex is excluded from release archives.
