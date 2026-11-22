"""Prod startup guard: the api must not run on a throwaway disk.

Railway no longer enforces a volume mount, so without this check a missing volume would silently
lose every upload on the next redeploy. Only the api process calls it (the scheduler has no volume).
"""

import os


class StorageVolumeError(RuntimeError):
    pass


def check_storage_volume(storage_dir: str, *, allow_ephemeral: bool = False) -> None:
    """Raise ``StorageVolumeError`` unless ``storage_dir`` exists, is writable and is a mount."""
    if not os.path.isdir(storage_dir):
        raise StorageVolumeError(
            f"STORAGE_DIR {storage_dir!r} does not exist; attach a volume mounted there"
        )
    if not os.access(storage_dir, os.W_OK | os.X_OK):
        raise StorageVolumeError(f"STORAGE_DIR {storage_dir!r} is not writable")
    if not allow_ephemeral and not os.path.ismount(storage_dir):
        raise StorageVolumeError(
            f"STORAGE_DIR {storage_dir!r} is not a mounted volume, so uploads would be lost on "
            "every redeploy. Attach a Railway volume at that path, or set "
            "STORAGE_ALLOW_EPHEMERAL=true to accept losing uploads"
        )
