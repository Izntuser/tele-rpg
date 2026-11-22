"""Prod startup guard: the api must not run on a throwaway disk.

Railway no longer enforces a volume mount, so without this check a missing volume would silently
lose every upload on the next redeploy. Only the api process calls it (the scheduler has no volume).
Railway exposes the attached volume's mount path as RAILWAY_VOLUME_MOUNT_PATH at runtime.
"""

import logging
import os

logger = logging.getLogger(__name__)


class StorageVolumeError(RuntimeError):
    pass


def _on_railway() -> bool:
    return any(k.startswith("RAILWAY_") for k in os.environ)


def check_storage_volume(storage_dir: str, *, allow_ephemeral: bool = False) -> None:
    """Raise ``StorageVolumeError`` unless ``storage_dir`` exists, is writable and is the volume."""
    if not os.path.isdir(storage_dir):
        raise StorageVolumeError(
            f"STORAGE_DIR {storage_dir!r} does not exist; attach a volume mounted there"
        )
    if not os.access(storage_dir, os.W_OK | os.X_OK):
        raise StorageVolumeError(f"STORAGE_DIR {storage_dir!r} is not writable")
    if allow_ephemeral:
        return
    mount = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if mount:
        if os.path.realpath(mount) != os.path.realpath(storage_dir):
            raise StorageVolumeError(
                f"Railway volume is mounted at {mount!r} but STORAGE_DIR is {storage_dir!r}; "
                "mount the volume at STORAGE_DIR (or set STORAGE_DIR to the mount path), or set "
                "STORAGE_ALLOW_EPHEMERAL=true to accept losing uploads"
            )
        return
    if _on_railway():
        raise StorageVolumeError(
            "no Railway volume attached to this service; "
            f"attach one at {storage_dir!r}, or set STORAGE_ALLOW_EPHEMERAL=true to accept "
            "losing uploads"
        )
    if not os.path.ismount(storage_dir):
        logger.warning(
            "STORAGE_DIR %r is not a mount point and this is not Railway; "
            "uploads may be lost on redeploy",
            storage_dir,
        )
