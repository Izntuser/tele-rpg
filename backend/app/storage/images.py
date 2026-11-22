"""Upload sanitizing: identify the image by its bytes, decode it, re-encode only the pixels.

The client's ``Content-Type`` and file name are ignored. An upload is accepted only when its
magic bytes are JPEG, PNG, WebP or HEIC/HEIF *and* Pillow decodes it as that same format.
The output is a brand-new image built from the decoded pixels (orientation applied first), so
EXIF (GPS, camera, timestamps), XMP, ICC profiles, comments and any trailing payload are gone.
Opaque images become JPEG, images with transparency WebP. Large images are scaled down.
"""

import io
import warnings
from dataclasses import dataclass

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: Decoded size limit (decompression bombs): about 40 megapixels.
MAX_PIXELS = 40_000_000
#: Longest side of the stored image.
MAX_SIDE = 2048
JPEG_QUALITY = 85
WEBP_QUALITY = 85

#: Pillow format names accepted for each sniffed type.
_PILLOW_FORMATS = {"jpeg": {"JPEG", "MPO"}, "png": {"PNG"}, "webp": {"WEBP"}, "heic": {"HEIF"}}
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


def process_image(data: bytes) -> ProcessedImage:
    """Validate and re-encode an upload. CPU-bound: call it in a worker thread."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageTooLargeError
    kind = sniff(data)
    if kind is None:
        raise UnsupportedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in _PILLOW_FORMATS[kind]:
                    raise UnsupportedImageError
                width, height = source.size
                if width <= 0 or height <= 0:
                    raise UnsupportedImageError
                if width * height > MAX_PIXELS:
                    raise ImageTooLargeError
                source.seek(0)  # first frame of an animated image
                upright = ImageOps.exif_transpose(source)
                upright.load()
    except (ImageTooLargeError, UnsupportedImageError):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageTooLargeError from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError):
        raise UnsupportedImageError from None

    alpha = _has_alpha(upright)
    pixels = upright.convert("RGBA" if alpha else "RGB")
    pixels.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    # A fresh image holds only the pixels: no info dict, EXIF, ICC profile or XMP carried over.
    clean = Image.new(pixels.mode, pixels.size)
    clean.paste(pixels)
    out = io.BytesIO()
    if alpha:
        clean.save(out, "WEBP", quality=WEBP_QUALITY)
        mime, extension = "image/webp", "webp"
    else:
        clean.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        mime, extension = "image/jpeg", "jpg"
    return ProcessedImage(out.getvalue(), mime, extension, clean.width, clean.height)
