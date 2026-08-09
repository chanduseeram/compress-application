from pathlib import Path
from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"}


def compress_image(src_path: str, dest_dir: str, mode: str) -> str:
    """
    mode: 'lossless' or 'lossy'
    Returns path to compressed output file.
    Lossless: re-encode as WebP lossless (guaranteed pixel-identical).
    Lossy: re-encode as WebP lossy quality=75 (visually near-identical, much smaller).
    Explicitly closes the decoded image buffer as soon as we're done with it
    instead of waiting on Python's garbage collector — keeps peak RAM lower
    when many images are processed back-to-back.
    """
    src = Path(src_path)
    img = Image.open(src)
    try:
        # Preserve alpha if present
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.mode else "RGB")

        out_name = src.stem + (".lossless.webp" if mode == "lossless" else ".webp")
        out_path = Path(dest_dir) / out_name

        if mode == "lossless":
            img.save(out_path, format="WEBP", lossless=True, quality=100, method=3)
        else:
            img.save(out_path, format="WEBP", lossless=False, quality=75, method=3)

        return str(out_path)
    finally:
        img.close()


def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS
