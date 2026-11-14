"""Build on the target OS; smoke-test the GUI before archiving public binaries."""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        required=True,
        choices=["windows-x64", "macos-arm64", "macos-x64", "linux-x64", "linux-arm64"],
    )
    label = parser.parse_args().platform
    expected_os, expected_arch = label.split("-")
    actual_os = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    actual_arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if (actual_os, actual_arch) != (expected_os, expected_arch):
        raise SystemExit("Build must run on the matching native OS and architecture")
    root = Path(__file__).resolve().parents[1]
    dist = root / "artifacts/companion-build/dist"
    output = root / "artifacts/companion-release"
    output.mkdir(parents=True, exist_ok=True)
    name = "rePlay-USB-Companion"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            name,
            "--paths",
            "src",
            "--distpath",
            str(dist),
            "--workpath",
            "artifacts/companion-build/work",
            "--specpath",
            "artifacts/companion-build",
            "src/rm_redraw/companion/desktop.py",
        ],
        cwd=root,
        check=True,
    )
    bundle = dist / (name + ".app" if actual_os == "macos" else name)
    executable = bundle / (
        "Contents/MacOS/" + name
        if actual_os == "macos"
        else name + (".exe" if actual_os == "windows" else "")
    )
    process = subprocess.Popen([str(executable)])
    try:
        time.sleep(5)
        if process.poll() is not None:
            raise RuntimeError("Packaged GUI exited during startup")
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)
    license_dir = bundle / "Contents/Resources" if actual_os == "macos" else bundle
    shutil.copyfile(root / "LICENSE", license_dir / "LICENSE-rePlay.txt")
    shutil.copyfile(root / "docs/usb-companion.md", license_dir / "COMPANION-GUIDE.md")
    asset = output / (name + "-" + label)
    if actual_os == "macos":
        archive = Path(str(asset) + ".zip")
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(archive)],
            check=True,
        )
    elif actual_os == "windows":
        archive = Path(shutil.make_archive(str(asset), "zip", dist, bundle.name))
    else:
        archive = Path(str(asset) + ".tar.gz")
        with tarfile.open(archive, "w:gz") as target:
            target.add(bundle, arcname=bundle.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + ".sha256")).write_text(
        digest + "  " + archive.name + "\n", encoding="utf-8"
    )
    print(f"Validated {archive.name}: {digest}")


if __name__ == "__main__":
    main()
