"""Upload sanitizing: identify the image by its bytes, decode it, re-encode only the pixels.

The client's ``Content-Type`` and file name are ignored. An upload is accepted only when its
magic bytes are JPEG, PNG, WebP or HEIC/HEIF *and* Pillow decodes it as that same format.
The output is a brand-new image built from the decoded pixels (orientation applied first), so
EXIF (GPS, camera, timestamps), XMP, ICC profiles, comments and any trailing payload are gone.
Opaque images become JPEG, images with transparency WebP. Large images are scaled down.

Memory: a decoded image costs up to 4 bytes per pixel, so the pixel caps below bound one
decode (~100 MB at the worst), JPEGs are decoded already scaled down (``Image.draft``), no
avoidable full-size copy is made, and ``process_image_bounded`` lets at most
``IMAGE_PROCESS_CONCURRENCY`` (default 2) decodes run at once per event loop.
"""

import asyncio
import contextlib
import io
import warnings
import weakref
from dataclasses import dataclass

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

pillow_heif.register_heif_opener()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: Size limit from the header (decompression bombs): about 40 megapixels. A 40 MP JPEG is
#: still affordable because it is decoded at 1/2..1/8 scale (``draft``); see below.
MAX_PIXELS = 40_000_000
#: Limit on what is actually decoded (after ``draft``): 24 MP is ~96 MB as RGBA. The client
#: compresses photos to 2048 px before upload, so real uploads stay far below either cap.
MAX_DECODED_PIXELS = 24_000_000
#: Longest side of the stored image.
MAX_SIDE = 2048
JPEG_QUALITY = 85
WEBP_QUALITY = 85

#: Pillow format names accepted for each sniffed type.
_PILLOW_FORMATS = {"jpeg": {"JPEG", "MPO"}, "png": {"PNG"}, "webp": {"WEBP"}, "heic": {"HEIF"}}
#: Pillow openers tried for each sniffed type (MPO has no opener of its own: the JPEG opener
#: returns it), so a JPEG-looking upload is never handed to any other decoder.
_OPEN_FORMATS = {"jpeg": ["JPEG"], "png": ["PNG"], "webp": ["WEBP"], "heic": ["HEIF"]}
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


class UnsupportedImageError(ValueError):
    """Not a JPEG/PNG/WebP/HEIC image, or it cannot be decoded (-> 415)."""


class ImageTooLargeError(ValueError):
    """More bytes or pixels than allowed (-> 413)."""


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    mime: str
    extension: str
    width: int
    height: int


def sniff(data: bytes) -> str | None:
    """The image type from the magic bytes, or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "heic"
    return None


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA", "PA"):
        low, _high = image.getchannel("A").getextrema()
        return isinstance(low, int | float) and low < 255
    return image.mode == "P" and "transparency" in image.info


def _fitted(width: int, height: int) -> tuple[int, int]:
    """The size ``thumbnail((MAX_SIDE, MAX_SIDE))`` will produce (rounded up)."""
    longest = max(width, height)
    if longest <= MAX_SIDE:
        return width, height
    return -(-width * MAX_SIDE // longest), -(-height * MAX_SIDE // longest)


def process_image(data: bytes) -> ProcessedImage:
    """Validate and re-encode an upload. CPU-bound and memory-heavy: call it through
    ``process_image_bounded``."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageTooLargeError
    kind = sniff(data)
    if kind is None:
        raise UnsupportedImageError
    formats = _PILLOW_FORMATS[kind]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=list(_OPEN_FORMATS[kind])) as source:
                if source.format not in formats:
                    raise UnsupportedImageError
                width, height = source.size
                if width <= 0 or height <= 0:
                    raise UnsupportedImageError
                if width * height > MAX_PIXELS:
                    raise ImageTooLargeError
                source.seek(0)  # first frame of an animated image
                if kind == "jpeg":
                    # Decode at the smallest 1/2, 1/4 or 1/8 scale still >= the stored size.
                    source.draft(None, _fitted(width, height))
                if source.width * source.height > MAX_DECODED_PIXELS:
                    raise ImageTooLargeError
                source.getexif()  # read the orientation before the pixels are replaced
                source.load()
                ImageOps.exif_transpose(source, in_place=True)
                alpha = _has_alpha(source)
                target = "RGBA" if alpha else "RGB"
                pixels = source if source.mode == target else source.convert(target)
                pixels.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                # A fresh image holds only the pixels: no info dict, EXIF, ICC profile or XMP.
                clean = Image.new(pixels.mode, pixels.size)
                clean.paste(pixels)
                del pixels
    except (ImageTooLargeError, UnsupportedImageError):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageTooLargeError from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise UnsupportedImageError from None

    out = io.BytesIO()
    if alpha:
        clean.save(out, "WEBP", quality=WEBP_QUALITY)
        mime, extension = "image/webp", "webp"
    else:
        clean.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        mime, extension = "image/jpeg", "jpg"
    return ProcessedImage(out.getvalue(), mime, extension, clean.width, clean.height)


#: One semaphore per event loop (an asyncio.Semaphore is bound to the loop it first waits on).
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(get_settings().image_process_concurrency)
        _semaphores[loop] = semaphore
    return semaphore


async def process_image_bounded(data: bytes) -> ProcessedImage:
    """``process_image`` in a worker thread, at most ``IMAGE_PROCESS_CONCURRENCY`` at a time.

    The slot is held until the thread really finishes, even if the request is cancelled
    (client gone), so cancelled uploads cannot pile up decodes beyond the bound."""
    async with _semaphore():
        work = asyncio.ensure_future(asyncio.to_thread(process_image, data))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            with contextlib.suppress(BaseException):
                await work
            raise
