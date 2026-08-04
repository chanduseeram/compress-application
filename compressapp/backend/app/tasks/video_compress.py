import subprocess
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def compress_video(src_path: str, dest_dir: str, mode: str) -> str:
    """
    mode: 'lossless' or 'lossy'
    Uses FFmpeg + HEVC (libx265).
    Lossless: -x265-params lossless=1 (pixel-exact, modest size win vs re-muxing).
    Lossy: CRF 28 (visually near-identical, big size win).
    """
    src = Path(src_path)
    out_name = src.stem + ("_lossless.mkv" if mode == "lossless" else "_compressed.mp4")
    out_path = Path(dest_dir) / out_name

    if mode == "lossless":
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx265", "-x265-params", "lossless=1",
            "-c:a", "copy",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx265", "-crf", "28", "-preset", "medium",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]

    subprocess.run(cmd, check=True, capture_output=True)
    return str(out_path)


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS
