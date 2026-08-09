import threading

_lock = threading.Lock()
_jobs = {}  # job_id -> {"state": ..., "current": int, "total": int, "file": str, "result": ..., "error": ...}


def create(job_id: str, total: int):
    with _lock:
        _jobs[job_id] = {"state": "PENDING", "current": 0, "total": total, "file": "", "result": None, "error": None}


def update_progress(job_id: str, current: int, file: str):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(state="PROGRESS", current=current, file=file)


def mark_success(job_id: str, result: dict):
    with _lock:
        _jobs[job_id].update(state="SUCCESS", result=result)


def mark_failure(job_id: str, error: str):
    with _lock:
        _jobs[job_id].update(state="FAILURE", error=error)


def get(job_id: str):
    with _lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None
