import React, { useState, useCallback, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "";

function humanSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  const units = ["KB", "MB", "GB"];
  let val = bytes;
  for (const u of units) {
    val /= 1024;
    if (val < 1024) return val.toFixed(1) + " " + u;
  }
  return val.toFixed(1) + " TB";
}

export default function App() {
  const [queue, setQueue] = useState([]); // {file, mode}
  const [phase, setPhase] = useState("idle"); // idle | uploading | processing | done | error
  const [progress, setProgress] = useState(null); // {current, total, file}
  const [result, setResult] = useState(null); // {zip_path, summary}
  const [jobId, setJobId] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef();

  const addFiles = useCallback((fileList) => {
    const arr = Array.from(fileList).map((f) => ({ file: f, mode: "lossy" }));
    setQueue((q) => [...q, ...arr]);
  }, []);

  const onDrop = (e) => {
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  };

  const setMode = (idx, mode) => {
    setQueue((q) => q.map((item, i) => (i === idx ? { ...item, mode } : item)));
  };

  const removeItem = (idx) => {
    setQueue((q) => q.filter((_, i) => i !== idx));
  };

  const poll = (jid) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API}/status/${jid}`);
        const data = await res.json();
        if (data.state === "PROGRESS" || data.state === "PENDING") {
          setProgress({ current: data.current, total: data.total, file: data.file });
        } else if (data.state === "SUCCESS") {
          clearInterval(interval);
          setResult(data.result);
          setPhase("done");
        } else if (data.state === "FAILURE") {
          clearInterval(interval);
          setError(data.error || "Processing failed");
          setPhase("error");
        }
      } catch (err) {
        clearInterval(interval);
        setError(String(err));
        setPhase("error");
      }
    }, 1200);
  };

  const startCompression = async () => {
    if (queue.length === 0) return;
    setPhase("uploading");
    setError(null);
    setResult(null);

    const form = new FormData();
    queue.forEach((item) => {
      form.append("files", item.file);
      form.append("modes", item.mode);
    });

    try {
      const res = await fetch(`${API}/upload`, { method: "POST", body: form });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      setPhase("processing");
      setProgress({ current: 0, total: queue.length, file: "" });
      poll(data.job_id);
    } catch (err) {
      setError(String(err));
      setPhase("error");
    }
  };

  const reset = () => {
    setQueue([]);
    setPhase("idle");
    setProgress(null);
    setResult(null);
    setJobId(null);
    setError(null);
  };

  const totalOriginal = result?.summary?.reduce((s, f) => s + f.original_size, 0) ?? 0;
  const totalCompressed = result?.summary?.reduce((s, f) => s + f.compressed_size, 0) ?? 0;
  const savedPct = totalOriginal > 0 ? (100 * (1 - totalCompressed / totalOriginal)).toFixed(1) : 0;

  return (
    <div className="app">
      <header className="header">
        <div className="wordmark">
          <span className="wordmark-main">shrink</span>
          <span className="wordmark-dot">.</span>
          <span className="wordmark-tail">zip</span>
        </div>
        <p className="tagline">Upload images and video. Choose lossless or lossy per file. Download one archive.</p>
      </header>

      {phase === "idle" && (
        <>
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            onClick={() => inputRef.current.click()}
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept="image/*,video/*"
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
            <div className="dropzone-inner">
              <div className="dropzone-icon">＋</div>
              <p>Drop files here or click to browse</p>
              <p className="dropzone-hint">JPG · PNG · WebP · MP4 · MOV · MKV</p>
            </div>
          </div>

          {queue.length > 0 && (
            <div className="queue">
              {queue.map((item, idx) => (
                <div className="queue-row" key={idx}>
                  <span className="queue-name">{item.file.name}</span>
                  <span className="queue-size">{humanSize(item.file.size)}</span>
                  <div className="mode-toggle">
                    <button
                      className={item.mode === "lossless" ? "active" : ""}
                      onClick={() => setMode(idx, "lossless")}
                    >
                      Lossless
                    </button>
                    <button
                      className={item.mode === "lossy" ? "active" : ""}
                      onClick={() => setMode(idx, "lossy")}
                    >
                      Lossy
                    </button>
                  </div>
                  <button className="remove-btn" onClick={() => removeItem(idx)} aria-label="Remove file">
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {queue.length > 0 && (
            <button className="primary-btn" onClick={startCompression}>
              Compress {queue.length} file{queue.length > 1 ? "s" : ""}
            </button>
          )}
        </>
      )}

      {(phase === "uploading" || phase === "processing") && (
        <div className="status-panel">
          <div className="spinner" />
          <p className="status-text">
            {phase === "uploading"
              ? "Uploading files…"
              : progress
              ? `Compressing ${progress.current + 1} of ${progress.total}${
                  progress.file ? ` — ${progress.file}` : ""
                }`
              : "Processing…"}
          </p>
        </div>
      )}

      {phase === "done" && result && (
        <div className="result-panel">
          <div className="result-stat">
            <span className="result-pct">{savedPct}%</span>
            <span className="result-label">smaller</span>
          </div>
          <div className="result-sizes">
            <span>{humanSize(totalOriginal)}</span>
            <span className="arrow">→</span>
            <span>{humanSize(totalCompressed)}</span>
          </div>
          <table className="result-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Mode</th>
                <th>Original</th>
                <th>Compressed</th>
              </tr>
            </thead>
            <tbody>
              {result.summary.map((f, i) => (
                <tr key={i}>
                  <td>{f.file}</td>
                  <td className="mode-cell">{f.mode}</td>
                  <td>{humanSize(f.original_size)}</td>
                  <td>{humanSize(f.compressed_size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="result-actions">
            <a className="primary-btn" href={`${API}/download/${jobId}`} download>
              Download archive
            </a>
            <button className="secondary-btn" onClick={reset}>
              Start over
            </button>
          </div>
        </div>
      )}

      {phase === "error" && (
        <div className="error-panel">
          <p>Something went wrong: {error}</p>
          <button className="secondary-btn" onClick={reset}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
