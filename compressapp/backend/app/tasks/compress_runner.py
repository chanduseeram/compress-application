import gc
import zipfile
from pathlib import Path

from app import job_store, storage
from app.tasks.image_compress import compress_image, is_image
from app.tasks.video_compress import compress_video, is_video

# Chunked video encoding keeps RAM bounded regardless of video length, so
# the real ceiling is disk space, not memory. Render free tier disk is small;
# this guards against filling it rather than a RAM concern.
MAX_VIDEO_MB = 500


def process_batch(job_id: str, file_specs: list[dict], output_dir: str):
    """
    Runs in-process via FastAPI BackgroundTasks (no Celery/Redis).
    Each file is isolated: one failure is recorded and skipped, the rest
    of the batch continues. Job only fails outright if every file fails,
    or if zip/upload itself fails.
    """
    total = len(file_specs)
    compressed_paths = []
    summary = []
    failures = []

    for i, spec in enumerate(file_specs):
        job_store.update_progress(job_id, i, spec["original_name"])

        path, mode, name = spec["path"], spec["mode"], spec["original_name"]

        try:
            orig_size = Path(path).stat().st_size

            if is_video(path) and orig_size > MAX_VIDEO_MB * 1024 * 1024:
                raise RuntimeError(
                    f"File is {orig_size / 1024 / 1024:.0f}MB — over the "
                    f"{MAX_VIDEO_MB}MB disk-space limit on this server. Skipped."
                )

            if is_image(path):
                out = compress_image(path, output_dir, mode)
            elif is_video(path):
                out = compress_video(path, output_dir, mode)
            else:
                out = path

            new_size = Path(out).stat().st_size
            compressed_paths.append(out)
            summary.append({
                "file": name,
                "mode": mode,
                "original_size": orig_size,
                "compressed_size": new_size,
            })

        except Exception as e:
            failures.append({"file": name, "error": str(e)})

        finally:
            # Free the original upload as soon as we're done with it —
            # frees both RAM (any buffers) and disk (limited on free tier).
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
            gc.collect()

    if not compressed_paths:
        # Every single file failed — this is a real job failure.
        detail = "; ".join(f"{f['file']}: {f['error']}" for f in failures)
        job_store.mark_failure(job_id, detail or "All files failed to process")
        return

    try:
        zip_path = Path(output_dir) / f"{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in compressed_paths:
                zf.write(p, arcname=Path(p).name)

        r2_key = f"jobs/{job_id}.zip"
        storage.upload_file(str(zip_path), r2_key)

        job_store.mark_success(job_id, {
            "r2_key": r2_key,
            "summary": summary,
            "failures": failures,  # partial failures, batch still succeeded
        })

    except Exception as e:
        job_store.mark_failure(job_id, f"Zip/upload step failed: {e}")
