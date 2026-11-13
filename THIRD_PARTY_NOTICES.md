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

The optional Rust pencil kernel has no third-party Cargo dependencies. The Rust toolchain is a build dependency and is not bundled.

## References versus dependencies

The calibration article discusses other open-source renderers and brush engines. Merely listing a project as a research reference does not make it a dependency. In particular, `rmc`, `librm_lines`, Quill, RMRender and inkterop are not runtime requirements of this package. Claims and license descriptions for those references are separately sourced in `docs/renderer-landscape.md`.

## Project and artwork terms

The project code and documentation are MIT-licensed; see LICENSE. Selected artwork requires separate owner review before publication. Existing tablet documents, reference exports and visual comparison artifacts are not included in the package. They are not covered by any future code license merely because they were used for local testing. The private visual annex is excluded from release archives.
