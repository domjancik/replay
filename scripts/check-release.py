"""Inspect release archives without extracting them; emit machine-readable evidence."""

import argparse
import configparser
import hashlib
import json
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT_FILES = {
    "PKG-INFO",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".gitignore",
}
DOCS = {
    "install.md",
    "local-replay-utility.md",
    "contracts.md",
    "calibration-journey.md",
    "renderer-landscape.md",
    "publication-readiness.md",
}
SCRIPTS = {"start-replay.ps1", "setup.ps1", "check-release.py", "release-smoke.py"}
BAD_PARTS = {
    ".git",
    ".uv-cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "fixtures",
    "artifacts",
    "plans",
    ".venv",
    ".agents",
    ".codex",
}
BAD_SUFFIXES = {".pyc", ".rmdoc", ".pdf", ".png", ".mp4", ".rm", ".pem", ".key"}


def allowed_package(name):
    return name.endswith(".py") or name in {
        "rm_redraw/web/static/index.html",
        "rm_redraw/web/static/app.js",
        "rm_redraw/web/static/style.css",
    }


def allowed_source(name):
    parts = PurePosixPath(name).parts
    if len(parts) == 1:
        return name in ROOT_FILES
    if parts[0] == "docs":
        return len(parts) == 2 and parts[1] in DOCS
    if parts[0] == "scripts":
        return len(parts) == 2 and parts[1] in SCRIPTS
    if parts[:2] == ("src", "rm_redraw"):
        return allowed_package("/".join(parts[1:]))
    if parts[0] == "tests":
        return name.endswith(".py")
    if parts[:2] == ("native", "pencil-kernel"):
        return (len(parts) == 3 and parts[2] in {"Cargo.toml", "Cargo.lock", "README.md"}) or (
            len(parts) == 4 and parts[2] in {"src", "tests"} and name.endswith(".rs")
        )
    return False


def safe(name):
    p = PurePosixPath(name)
    return (
        bool(name)
        and not p.is_absolute()
        and "\\" not in name
        and not any(x in ("..", ".") or x in BAD_PARTS for x in p.parts)
        and p.suffix.lower() not in BAD_SUFFIXES
    )


def inspect(path, require_license):
    errors, files, payloads = [], [], {}
    kind = "wheel" if path.suffix == ".whl" else "sdist"
    if kind == "wheel":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                files.append(name)
                if stat.S_ISLNK(info.external_attr >> 16):
                    errors.append(f"symlink: {name}")
                parts = PurePosixPath(name).parts
                metadata = (
                    len(parts) >= 2
                    and parts[0].startswith("rm_redraw-")
                    and parts[0].endswith(".dist-info")
                )
                if not safe(name) or not (
                    name.startswith("rm_redraw/") and allowed_package(name) or metadata
                ):
                    errors.append(f"unexpected path: {name}")
                if name.endswith("entry_points.txt"):
                    payloads["entry"] = archive.read(info).decode("utf-8")
    else:
        with tarfile.open(path, "r:gz") as archive:
            roots = set()
            for info in archive:
                parts = PurePosixPath(info.name).parts
                if len(parts) < 2:
                    if not info.isdir() or not safe(info.name):
                        errors.append(f"unexpected top-level member: {info.name}")
                    else:
                        roots.add(parts[0])
                    continue
                roots.add(parts[0])
                name = "/".join(parts[1:])
                if info.isdir():
                    continue
                files.append(name)
                if not info.isfile():
                    errors.append(f"non-regular member: {name}")
                if not safe(info.name) or not safe(name) or not allowed_source(name):
                    errors.append(f"unexpected path: {name}")
            if len(roots) != 1:
                errors.append("sdist must have exactly one top-level directory")
    if len(files) != len(set(files)):
        errors.append("duplicate archive member")
    if kind == "wheel":
        for asset in ("index.html", "app.js", "style.css"):
            if f"rm_redraw/web/static/{asset}" not in files:
                errors.append(f"missing static asset: {asset}")
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read_string(payloads.get("entry", ""))
            entry = config.get("console_scripts", "rm-redraw", fallback="")
        except configparser.Error:
            entry = ""
        if entry.strip() != "rm_redraw.web.__main__:main":
            errors.append("missing or incorrect rm-redraw entrypoint")
    if require_license and not any(PurePosixPath(x).name == "LICENSE" for x in files):
        errors.append("missing license")
    return {
        "path": str(path),
        "kind": kind,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "members": sorted(files),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--require-license", action="store_true")
    args = parser.parse_args()
    reports = []
    for path in args.archives:
        try:
            reports.append(inspect(path, args.require_license))
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
            reports.append({"path": str(path), "errors": [str(error)]})
    print(json.dumps({"artifacts": reports}, indent=2))
    return int(any(r["errors"] for r in reports))


if __name__ == "__main__":
    raise SystemExit(main())
