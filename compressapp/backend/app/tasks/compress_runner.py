import zipfile
from pathlib import Path

from app import job_store, storage
from app.tasks.image_compress import compress_image, is_image
from app.tasks.video_compress import compress_video, is_video


def process_batch(job_id: str, file_specs: list[dict], output_dir: str):
    """
    Runs in-process via FastAPI BackgroundTasks (no Celery/Redis).
    Compresses each file per its mode, zips outputs, uploads zip to R2,
    updates job_store as it goes.
    """
    total = len(file_specs)
    compressed_paths = []
    summary = []

    try:
        for i, spec in enumerate(file_specs):
            job_store.update_progress(job_id, i, spec["original_name"])

            path, mode = spec["path"], spec["mode"]
            orig_size = Path(path).stat().st_size

            if is_image(path):
                out = compress_image(path, output_dir, mode)
            elif is_video(path):
                out = compress_video(path, output_dir, mode)
            else:
                out = path

            new_size = Path(out).stat().st_size
            compressed_paths.append(out)
            summary.append({
                "file": spec["original_name"],
                "mode": mode,
                "original_size": orig_size,
                "compressed_size": new_size,
            })

        zip_path = Path(output_dir) / f"{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in compressed_paths:
                zf.write(p, arcname=Path(p).name)

        r2_key = f"jobs/{job_id}.zip"
        storage.upload_file(str(zip_path), r2_key)

        job_store.mark_success(job_id, {"r2_key": r2_key, "summary": summary})

    except Exception as e:
        job_store.mark_failure(job_id, str(e))
