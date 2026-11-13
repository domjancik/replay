import io
import json
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check-release.py"


def test_cloud_setup_docs_are_in_source_release(tmp_path):
    root = CHECKER.parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    for name in ("cloud-connector.md", "cloud-app-feasibility.md", "wasm-feasibility.md"):
        assert f"/docs/{name}" in included
        wheel, sdist = archives(tmp_path, f"docs/{name}")
        result = run_check(wheel, sdist)
        assert result.returncode == 0, result.stdout


def test_browser_cloud_sources_are_allowed_in_release(tmp_path):
    for name in ("cloud-ui.mjs", "cloud-client.mjs", "cloud-vault.mjs"):
        wheel, sdist = archives(tmp_path, f"src/rm_redraw/web/static/{name}")
        with zipfile.ZipFile(wheel, "a") as package:
            package.writestr(f"rm_redraw/web/static/{name}", "// synthetic module")
        assert run_check(wheel, sdist).returncode == 0
    for name in ("cloud-client.test.mjs", "cloud-vault.test.mjs", "cloud-ui.test.mjs"):
        wheel, sdist = archives(tmp_path, f"tests/web/{name}")
        assert run_check(wheel, sdist).returncode == 0


def test_wasm_reproduction_sources_are_in_source_release(tmp_path):
    root = CHECKER.parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    for name in (
        "Cargo.toml",
        "Cargo.lock",
        "src/lib.rs",
        "pencil.mjs",
        "pencil.test.mjs",
        "make_goldens.py",
    ):
        path = f"native/wasm-prototype/{name}"
        assert f"/{path}" in included
        wheel, sdist = archives(tmp_path, path)
        result = run_check(wheel, sdist)
        assert result.returncode == 0, result.stdout
    wheel, sdist = archives(tmp_path, "native/wasm-prototype/unreviewed.wasm")
    assert run_check(wheel, sdist).returncode != 0


def test_browser_and_pairing_prototype_sources_are_reviewed(tmp_path):
    root = CHECKER.parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    for path in (
        "native/browser-prototype/worker.mjs",
        "native/video-prototype/package-lock.json",
        "native/rmctl-pairing/code-stdin.patch",
        "native/rmctl-pairing/LICENSE",
    ):
        assert f"/{path}" in included
        wheel, sdist = archives(tmp_path, path)
        assert run_check(wheel, sdist).returncode == 0
    for path in (
        "native/browser-prototype/unreviewed.zip",
        "native/video-prototype/node_modules/anything.js",
        "native/rmctl-pairing/token.json",
    ):
        wheel, sdist = archives(tmp_path, path)
        assert run_check(wheel, sdist).returncode != 0


def test_rust_renderer_release_includes_sources_not_generated_wasm(tmp_path):
    root = CHECKER.parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/native/renderer/src" in included
    assert "/native/renderer/LICENSE-PILLOW" in included
    for path in (
        "native/renderer/src/render.rs",
        "native/renderer/src/bin/render-json.rs",
        "native/renderer/LICENSE-PILLOW",
        "native/renderer/Cargo.lock",
        "native/renderer/renderer.mjs",
        "native/renderer/browser/worker.mjs",
        "native/renderer/tests/raster_differential.mjs",
        "docs/rust-renderer.md",
    ):
        wheel, sdist = archives(tmp_path, path)
        assert run_check(wheel, sdist).returncode == 0
    wheel, sdist = archives(tmp_path, "native/renderer/target/release/renderer.wasm")
    assert run_check(wheel, sdist).returncode != 0


def archives(tmp_path, extra=None, entry=True, license=False):
    wheel = tmp_path / "rm_redraw-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "rm_redraw-0.1.0.tar.gz"
    wheel_files = {
        "rm_redraw/__init__.py": b"",
        "rm_redraw/web/static/index.html": b"index",
        "rm_redraw/web/static/app.js": b"js",
        "rm_redraw/web/static/style.css": b"css",
        "rm_redraw-0.1.0.dist-info/entry_points.txt": (
            b"[console_scripts]\nrm-redraw = rm_redraw.web.__main__:main\n" if entry else b""
        ),
    }
    source_files = {"README.md": b"readme", "pyproject.toml": b"project"}
    if license:
        wheel_files["rm_redraw-0.1.0.dist-info/licenses/LICENSE"] = b"license"
        source_files["LICENSE"] = b"license"
    with zipfile.ZipFile(wheel, "w") as z:
        for name, data in wheel_files.items():
            z.writestr(name, data)
    with tarfile.open(sdist, "w:gz") as tar:
        for name, data in source_files.items():
            item = tarfile.TarInfo("rm_redraw-0.1.0/" + name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
        if extra:
            item = tarfile.TarInfo("rm_redraw-0.1.0/" + extra)
            item.size = 1
            tar.addfile(item, io.BytesIO(b"x"))
    return wheel, sdist


def run_check(*args):
    return subprocess.run(
        [sys.executable, str(CHECKER), *map(str, args)], capture_output=True, text=True
    )


def test_clean_archive_report_and_license_gate(tmp_path):
    wheel, sdist = archives(tmp_path)
    result = run_check(wheel, sdist)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["artifacts"]) == 2
    assert all(len(a["sha256"]) == 64 for a in report["artifacts"])
    result = run_check(wheel, sdist, "--require-license")
    assert result.returncode != 0
    assert "license" in result.stdout.lower()


def test_reject_private_and_history_paths(tmp_path):
    wheel, sdist = archives(tmp_path, "plans/private.md")
    result = run_check(wheel, sdist)
    assert result.returncode != 0
    assert "plans/private.md" in result.stdout


def test_reject_missing_entrypoint(tmp_path):
    wheel, sdist = archives(tmp_path, entry=False)
    result = run_check(wheel, sdist)
    assert result.returncode != 0
    assert "entrypoint" in result.stdout.lower()


def test_offline_release_smoke_exercises_http_jobs_and_export(tmp_path):
    smoke = CHECKER.with_name("release-smoke.py")
    result = subprocess.run(
        [sys.executable, str(smoke), "--allow-source"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["http"]["session"] and evidence["http"]["assets"]
    assert evidence["http"]["video_range"]
    assert evidence["replay"]["final_frame_matches_static"]
    assert evidence["export"]["forward_final_frame_matches_static"]
    assert evidence["export"]["loop_seam_matches"]


def test_reject_symlink_and_private_nested_under_allowed_tree(tmp_path):
    wheel, sdist = archives(tmp_path, "tests/fixtures/private/secret.txt")
    with zipfile.ZipFile(wheel, "a") as z:
        info = zipfile.ZipInfo("rm_redraw/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        z.writestr(info, "target")
    result = run_check(wheel, sdist)
    assert result.returncode != 0
    assert "symlink" in result.stdout
    assert "private/secret.txt" in result.stdout


def test_reject_lookalike_distribution_metadata(tmp_path):
    wheel, sdist = archives(tmp_path)
    with zipfile.ZipFile(wheel, "a") as z:
        z.writestr("attacker/other.dist-info/secret", "x")
    result = run_check(wheel, sdist)
    assert result.returncode != 0
    assert "attacker/other.dist-info/secret" in result.stdout


def test_generated_sdist_metadata_is_permitted(tmp_path):
    wheel, sdist = archives(tmp_path, "PKG-INFO")
    result = run_check(wheel, sdist)
    assert result.returncode == 0, result.stdout


def test_reject_unexpected_files_inside_source_package(tmp_path):
    wheel, sdist = archives(tmp_path, "src/rm_redraw/secret.txt")
    result = run_check(wheel, sdist)
    assert result.returncode != 0
    assert "src/rm_redraw/secret.txt" in result.stdout


def test_reject_loose_top_level_private_file(tmp_path):
    wheel, sdist = archives(tmp_path)
    rewritten = tmp_path / "loose.tar.gz"
    with tarfile.open(sdist) as source, tarfile.open(rewritten, "w:gz") as target:
        for item in source:
            target.addfile(item, source.extractfile(item))
        extra = tarfile.TarInfo("secret.pem")
        extra.size = 6
        target.addfile(extra, io.BytesIO(b"secret"))
    result = run_check(wheel, rewritten)
    assert result.returncode != 0
    assert "secret.pem" in result.stdout
