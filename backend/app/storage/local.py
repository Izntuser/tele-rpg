"""``StorageBackend`` on a local directory (``STORAGE_DIR``; a Railway volume in prod).

Path safety: a key must match ``KEY_PATTERN`` (no ``..``, no absolute paths, no backslashes)
and the resolved path must still lie inside the root, so even a backend bug elsewhere cannot
read or write outside ``STORAGE_DIR``. Writes go to a temp file in the same directory and are
renamed into place, so a reader never sees a half-written file.
"""

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from app.storage.base import (
    CHUNK_SIZE,
    InvalidKeyError,
    StorageBackend,
    StoredFileNotFoundError,
    validate_key,
)


class LocalStorage(StorageBackend):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()

    def path_for(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise InvalidKeyError(key)
        return path

    def _write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def put(self, key: str, data: bytes) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(self._write, path, data)

    def open(self, key: str) -> AsyncIterator[bytes]:
        path = self.path_for(key)
        try:
            fh = path.open("rb")
        except (FileNotFoundError, IsADirectoryError):
            raise StoredFileNotFoundError(key) from None
        return self._chunks(fh)

    async def _chunks(self, fh: BinaryIO) -> AsyncIterator[bytes]:
        try:
            while chunk := await asyncio.to_thread(fh.read, CHUNK_SIZE):
                yield chunk
        finally:
            fh.close()

    async def delete(self, key: str) -> None:
        path = self.path_for(key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        path = self.path_for(key)
        return await asyncio.to_thread(path.is_file)
