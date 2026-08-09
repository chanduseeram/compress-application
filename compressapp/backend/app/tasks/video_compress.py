import gc
import json
import subprocess
import tempfile
import uuid
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

# Below this duration, chunking adds overhead for no benefit — just encode directly.
CHUNK_THRESHOLD_SECONDS = 30
CHUNK_LENGTH_SECONDS = 15

# Cap resolution during encode — a single chunk at 4K/1440p/1080p can spike
# RAM past 512MB regardless of duration. Measured on this exact server:
# preset=faster @ 1080p peaked at ~590MB (over budget); preset=ultrafast @
# 720p peaked at ~260MB (safe margin under Python/uvicorn's own baseline).
# This does reduce visual resolution for large source video — a real
# tradeoff, chosen deliberately to stay inside the free-tier RAM ceiling.
MAX_HEIGHT = 720


def is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def get_duration(path: str) -> float:
    """ffprobe the video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    data = json.loads(out.stdout)
    return float(data["format"]["duration"])


def _encode_args(mode: str) -> list[str]:
    """Shared low-memory encode settings for both chunked and direct paths."""
    # Downscale only if the source exceeds MAX_HEIGHT — never upscale.
    scale_filter = f"scale=-2:'min({MAX_HEIGHT},ih)'"
    if mode == "lossless":
        # Lossless mode intentionally skips the scale filter — "lossless"
        # should mean pixel-identical, not pixel-identical-but-smaller.
        return ["-c:v", "libx265", "-x265-params", "lossless=1", "-threads", "1", "-c:a", "copy"]
    return [
        "-vf", scale_filter,
        "-c:v", "libx265", "-crf", "28", "-preset", "ultrafast", "-threads", "1",
        "-c:a", "aac", "-b:a", "128k",
    ]


def _encode_single(src: str, out_path: str, mode: str) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(src), *_encode_args(mode), str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)


def compress_video(src_path: str, dest_dir: str, mode: str) -> str:
    """
    mode: 'lossless' or 'lossy'
    Long videos are split into short chunks, encoded one at a time (low peak
    RAM), then concatenated back into a single output file. Each chunk's
    files are deleted as soon as it's no longer needed.
    """
    src = Path(src_path)
    ext = ".mkv" if mode == "lossless" else ".mp4"
    out_name = src.stem + ("_lossless" if mode == "lossless" else "_compressed") + ext
    out_path = Path(dest_dir) / out_name

    duration = get_duration(str(src))

    if duration <= CHUNK_THRESHOLD_SECONDS:
        _encode_single(str(src), str(out_path), mode)
        return str(out_path)

    # --- chunked path ---
    work_dir = Path(tempfile.mkdtemp(prefix=f"chunks_{uuid.uuid4().hex[:8]}_"))
    try:
        # Split in a single pass via the segment muxer — unlike manual -ss
        # loops, this doesn't duplicate frames at chunk boundaries.
        raw_pattern = work_dir / f"raw_%04d{src.suffix}"
        split_cmd = [
            "ffmpeg", "-y", "-i", str(src), "-c", "copy", "-map", "0",
            "-f", "segment", "-segment_time", str(CHUNK_LENGTH_SECONDS),
            "-reset_timestamps", "1", str(raw_pattern),
        ]
        subprocess.run(split_cmd, check=True, capture_output=True)

        raw_chunks = sorted(work_dir.glob(f"raw_*{src.suffix}"))
        if not raw_chunks:
            raise RuntimeError("Video splitting produced no segments")

        compressed_chunk_paths = []

        for i, raw_chunk in enumerate(raw_chunks):
            compressed_chunk = work_dir / f"done_{i:04d}{ext}"

            # Compress just this short chunk (small, bounded memory use)
            _encode_single(str(raw_chunk), str(compressed_chunk), mode)

            # Free the raw chunk immediately — don't hold it past this point
            raw_chunk.unlink(missing_ok=True)
            gc.collect()

            compressed_chunk_paths.append(compressed_chunk)

        if not compressed_chunk_paths:
            raise RuntimeError("Video chunking produced no valid segments")

        # Concat all compressed chunks back into one file.
        #    Same codec/params across chunks, so this is a fast stream copy.
        concat_list = work_dir / "concat_list.txt"
        with concat_list.open("w") as f:
            for p in compressed_chunk_paths:
                f.write(f"file '{p}'\n")

        concat_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(out_path),
        ]
        subprocess.run(concat_cmd, check=True, capture_output=True)

        # Free the compressed chunks now that they're merged
        for p in compressed_chunk_paths:
            p.unlink(missing_ok=True)

        return str(out_path)

    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
