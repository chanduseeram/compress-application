import os
import re
import time
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, Query, Request
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

# Restrict to the real frontend domain in production. "*" is fine for local
# dev but on a live app it lets any website's JS call this API using a
# visitor's browser. Set FRONTEND_URL env var on Render to lock this down.
ALLOWED_ORIGINS = os.environ.get("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGINS] if ALLOWED_ORIGINS != "*" else ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MAX_REQUEST_MB = 600  # reject oversized uploads before writing anything to disk
RATE_LIMIT_PER_HOUR = 20  # per-IP upload requests

_rate_limit_log: dict[str, list[float]] = {}


def _check_rate_limit(ip: str):
    now = time.time()
    hits = _rate_limit_log.setdefault(ip, [])
    hits[:] = [t for t in hits if now - t < 3600]  # keep last hour only
    if len(hits) >= RATE_LIMIT_PER_HOUR:
        return False
    hits.append(now)
    return True


def _safe_filename(name: str) -> str:
    """
    Strip any directory components and dangerous characters from a
    user-supplied filename before it's used to build a filesystem path.
    Prevents path traversal (e.g. "../../etc/x") from escaping the
    intended upload folder.
    """
    name = Path(name).name  # drops any ../ or / or \ path components
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip()
    return name or f"file_{uuid.uuid4().hex[:8]}"


@app.post("/upload")
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    modes: list[str] = Form(...),
):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            {"error": f"Rate limit exceeded — max {RATE_LIMIT_PER_HOUR} uploads per hour."},
            status_code=429,
        )

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_MB * 1024 * 1024:
        return JSONResponse(
            {"error": f"Upload too large — max {MAX_REQUEST_MB}MB per batch."},
            status_code=413,
        )

    job_id = str(uuid.uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    file_specs = []
    for f, mode in zip(files, modes):
        safe_name = _safe_filename(f.filename)
        dest = job_dir / safe_name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        file_specs.append({"path": str(dest), "mode": mode, "original_name": safe_name})

    job_store.create(job_id, total=len(file_specs))
    background_tasks.add_task(process_batch, job_id, file_specs, str(OUTPUT_DIR))

    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        return JSONResponse({"error": "unknown job_id"}, status_code=404)
    return job


def _sanitize_filename(name: str) -> str:
    """Strip anything that isn't safe in a Content-Disposition filename."""
    name = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    if not name:
        name = "compressed"
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return name


@app.get("/download/{job_id}")
async def download(job_id: str, filename: str | None = Query(None)):
    job = job_store.get(job_id)
    if job is None or job["state"] != "SUCCESS":
        return JSONResponse({"error": "not ready"}, status_code=404)

    final_name = _sanitize_filename(filename) if filename else job["result"]["default_filename"]
    url = storage.presigned_download_url(job["result"]["r2_key"], filename=final_name)
    return RedirectResponse(url)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/ffmpeg")
async def debug_ffmpeg():
    """
    Visit this URL directly in a browser to confirm ffmpeg is actually
    installed on the running server — no shell access needed.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=10
        )
        return {
            "ffmpeg_installed": True,
            "version_output": result.stdout.splitlines()[0] if result.stdout else "",
        }
    except FileNotFoundError:
        return JSONResponse(
            {"ffmpeg_installed": False, "error": "ffmpeg not found on PATH"},
            status_code=500,
        )
    except Exception as e:
        return JSONResponse(
            {"ffmpeg_installed": False, "error": str(e)},
            status_code=500,
        )
