import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from app import job_store, storage
from app.tasks.compress_runner import process_batch

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Compress App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload")
async def upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    modes: list[str] = Form(...),
):
    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    file_specs = []
    for f, mode in zip(files, modes):
        dest = job_dir / f.filename
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        file_specs.append({"path": str(dest), "mode": mode, "original_name": f.filename})

    job_store.create(job_id, total=len(file_specs))
    background_tasks.add_task(process_batch, job_id, file_specs, str(OUTPUT_DIR))

    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        return JSONResponse({"error": "unknown job_id"}, status_code=404)
    return job


@app.get("/download/{job_id}")
async def download(job_id: str):
    job = job_store.get(job_id)
    if job is None or job["state"] != "SUCCESS":
        return JSONResponse({"error": "not ready"}, status_code=404)
    url = storage.presigned_download_url(job["result"]["r2_key"])
    return RedirectResponse(url)


@app.get("/health")
async def health():
    return {"status": "ok"}
