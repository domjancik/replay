"""Fetch only the approved public landing-page examples, verifying their hashes."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "native/hosted/examples.json").read_text(encoding="utf-8"))
output = root / "artifacts/landing-examples"
output.mkdir(parents=True, exist_ok=True)
for item in manifest["files"]:
    target = output / item["name"]
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]:
        continue
    with urlopen(item["url"], timeout=60) as response:
        data = response.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Public example checksum mismatch: " + item["name"])
    target.write_bytes(data)
    print("Verified", item["name"])
