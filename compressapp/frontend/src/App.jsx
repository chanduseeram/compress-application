import React, { useState, useCallback, useRef, useMemo } from "react";

const API = import.meta.env.VITE_API_URL || "";

// Rough, honest estimates — actual ratio varies a lot by content.
const LOSSY_RATIO = 0.4;
const LOSSLESS_RATIO = 0.85;

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

function humanTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.ceil(seconds % 60);
  return `${m}m ${s}s`;
}

const SUPPORTED_EXT = /\.(jpe?g|png|webp|bmp|tiff|mp4|mov|mkv|avi|webm)$/i;

export default function App() {
  const [queue, setQueue] = useState([]); // {file, mode}
  const [phase, setPhase] = useState("idle"); // idle | uploading | processing | done | error
  const [uploadPct, setUploadPct] = useState(0);
  const [progress, setProgress] = useState(null); // {current, total, file}
  const [etaSeconds, setEtaSeconds] = useState(null);
  const [result, setResult] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [zipName, setZipName] = useState("");
  const [error, setError] = useState(null);
  const inputRef = useRef();
  const folderInputRef = useRef();
  const xhrRef = useRef(null);
  const processingStart = useRef(null);

  const addFiles = useCallback((fileList) => {
    const arr = Array.from(fileList)
      .filter((f) => SUPPORTED_EXT.test(f.name))
      .map((f) => ({ file: f, mode: "lossy" }));
    setQueue((q) => [...q, ...arr]);
  }, []);

  const onDrop = (e) => {
    e.preventDefault();
    addFiles(e.dataTransfer.files);
  };

  const setMode = (idx, mode) => {
    setQueue((q) => q.map((item, i) => (i === idx ? { ...item, mode } : item)));
  };

  const setAllModes = (mode) => {
    setQueue((q) => q.map((item) => ({ ...item, mode })));
  };

  const removeItem = (idx) => {
    setQueue((q) => q.filter((_, i) => i !== idx));
  };

  const totals = useMemo(() => {
    const originalBytes = queue.reduce((s, q) => s + q.file.size, 0);
    const lossyBytes = queue.reduce(
      (s, q) => s + (q.mode === "lossy" ? q.file.size * LOSSY_RATIO : q.file.size * LOSSLESS_RATIO),
      0
    );
    return { originalBytes, estimatedBytes: lossyBytes };
  }, [queue]);

  const poll = (jid) => {
    processingStart.current = Date.now();
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API}/status/${jid}`);
        if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
        const data = await res.json();

        if (data.state === "PROGRESS" || data.state === "PENDING") {
          setProgress({ current: data.current, total: data.total, file: data.file });
          const elapsed = (Date.now() - processingStart.current) / 1000;
          const doneCount = Math.max(data.current, 1);
          const perFile = elapsed / doneCount;
          const remaining = Math.max(data.total - data.current, 0);
          setEtaSeconds(perFile * remaining);
        } else if (data.state === "SUCCESS") {
          clearInterval(interval);
          setResult(data.result);
          setZipName(data.result.default_filename?.replace(/\.zip$/i, "") || "compressed");
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

  const startCompression = () => {
    if (queue.length === 0) return;
    setPhase("uploading");
    setUploadPct(0);
    setError(null);
    setResult(null);

    const form = new FormData();
    queue.forEach((item) => {
      form.append("files", item.file);
      form.append("modes", item.mode);
    });

    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    xhr.open("POST", `${API}/upload`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        setUploadPct(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        setError(`Upload failed: ${xhr.status}`);
        setPhase("error");
        return;
      }
      const data = JSON.parse(xhr.responseText);
      setJobId(data.job_id);
      setPhase("processing");
      setProgress({ current: 0, total: queue.length, file: "" });
      poll(data.job_id);
    };

    xhr.onerror = () => {
      setError("Upload failed — connection lost. If this was a large batch, try fewer files at once.");
      setPhase("error");
    };

    xhr.send(form);
  };

  const reset = () => {
    setQueue([]);
    setPhase("idle");
    setUploadPct(0);
    setProgress(null);
    setEtaSeconds(null);
    setResult(null);
    setJobId(null);
    setError(null);
  };

  const totalOriginal = result?.summary?.reduce((s, f) => s + f.original_size, 0) ?? 0;
  const totalCompressed = result?.summary?.reduce((s, f) => s + f.compressed_size, 0) ?? 0;
  const savedPct = totalOriginal > 0 ? (100 * (1 - totalCompressed / totalOriginal)).toFixed(1) : 0;
  const overallPct = progress && progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;

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
            <input
              ref={folderInputRef}
              type="file"
              multiple
              webkitdirectory=""
              directory=""
              hidden
              onChange={(e) => addFiles(e.target.files)}
            />
            <div className="dropzone-inner">
              <div className="dropzone-icon">＋</div>
              <p>Drop files here or click to browse</p>
              <p className="dropzone-hint">JPG · PNG · WebP · MP4 · MOV · MKV</p>
              <button
                className="folder-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  folderInputRef.current.click();
                }}
              >
                Or select a folder
              </button>
            </div>
          </div>

          {queue.length > 0 && (
            <>
              <div className="queue-header">
                <span>{queue.length} file{queue.length > 1 ? "s" : ""} selected</span>
                <div className="bulk-mode">
                  <button onClick={() => setAllModes("lossy")}>All lossy</button>
                  <button onClick={() => setAllModes("lossless")}>All lossless</button>
                </div>
              </div>

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

              <div className="estimate-panel">
                <span className="estimate-label">Estimated output</span>
                <div className="estimate-sizes">
                  <span>{humanSize(totals.originalBytes)}</span>
                  <span className="arrow">→</span>
                  <span>~{humanSize(totals.estimatedBytes)}</span>
                </div>
                <span className="estimate-note">Rough estimate — actual result varies by content.</span>
              </div>

              <button className="primary-btn" onClick={startCompression}>
                Compress {queue.length} file{queue.length > 1 ? "s" : ""}
              </button>
            </>
          )}

          <div className="explainer">
            <div className="explainer-col">
              <h3>Lossy</h3>
              <p>Smaller files, tiny quality tradeoff. Best for sharing, uploading, saving space.</p>
              <p className="explainer-example">500 MB → ~200 MB</p>
            </div>
            <div className="explainer-col">
              <h3>Lossless</h3>
              <p>Pixel-identical to the original. Larger files. Best for editing and archiving.</p>
              <p className="explainer-example">500 MB → ~300–425 MB</p>
            </div>
          </div>

          <div className="privacy-note">
            <span className="privacy-icon">🔒</span>
            <div>
              <p className="privacy-title">Your files aren't kept</p>
              <p className="privacy-body">
                Uploads and downloads travel over an encrypted connection (HTTPS). Your files
                are used only to generate your compressed download, then deleted from this
                server's disk immediately after processing. The download link is unique to
                your job and expires automatically after 1 hour.
              </p>
            </div>
          </div>
        </>
      )}

      {phase === "uploading" && (
        <div className="status-panel">
          <p className="status-text">Uploading… {uploadPct}%</p>
          <div className="progress-bar-track">
            <div className="progress-bar-fill" style={{ width: `${uploadPct}%` }} />
          </div>
        </div>
      )}

      {phase === "processing" && (
        <div className="status-panel">
          <p className="status-text">
            Compressing {progress ? `${progress.current + 1} / ${progress.total}` : ""}
            {progress?.file ? ` — ${progress.file}` : ""}
          </p>
          <div className="progress-bar-track">
            <div className="progress-bar-fill" style={{ width: `${overallPct}%` }} />
          </div>
          <div className="status-meta">
            <span>{overallPct}% complete</span>
            <span>ETA: {humanTime(etaSeconds)}</span>
          </div>
          <p className="wait-note">
            Large videos can take several minutes — this keeps running even if you switch
            tabs or do something else. Come back and this page will show your download.
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

          {result.failures && result.failures.length > 0 && (
            <div className="partial-warning">
              <p>{result.failures.length} file{result.failures.length > 1 ? "s" : ""} couldn't be processed and were skipped:</p>
              <ul>
                {result.failures.map((f, i) => (
                  <li key={i}><strong>{f.file}</strong> — {f.error}</li>
                ))}
              </ul>
            </div>
          )}

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
          <div className="rename-row">
            <label className="rename-label" htmlFor="zipname">File name</label>
            <div className="rename-input-wrap">
              <input
                id="zipname"
                type="text"
                value={zipName}
                onChange={(e) => setZipName(e.target.value)}
                className="rename-input"
              />
              <span className="rename-ext">.zip</span>
            </div>
          </div>
          <div className="result-actions">
            <a
              className="primary-btn"
              href={`${API}/download/${jobId}?filename=${encodeURIComponent((zipName || "compressed") + ".zip")}`}
            >
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
