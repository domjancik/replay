"""Bounded validation of raw notebook archives."""

import hashlib
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MAX_BYTES = 128 * 1024 * 1024


def archive_hashes(data: bytes) -> dict[str, str]:
    if len(data) > MAX_BYTES:
        raise ValueError("Notebook exceeds the 128 MiB limit")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 20000 or sum(i.file_size for i in infos) > 512 * 1024 * 1024:
                raise ValueError("Expanded notebook exceeds the local utility limit")
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                raise ValueError("Notebook has duplicate archive members")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                    raise ValueError("Notebook contains an unsafe archive member")
            return {
                i.filename: hashlib.sha256(archive.read(i)).hexdigest()
                for i in infos
                if not i.is_dir()
            }
    except BadZipFile as error:
        raise ValueError("Not a valid .rmdoc ZIP archive") from error
