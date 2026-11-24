import { useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import type { UploadLimits } from "../../types/api";
import type { UploadProgressEvent } from "../../api/client";

export type UploadPhase = "idle" | "uploading" | "validating";

interface AudioUploadZoneProps {
  limits: UploadLimits;
  phase: UploadPhase;
  progress: UploadProgressEvent | null;
  error: { code: string; message: string } | null;
  onFileSelected: (file: File) => void;
  onCancelUpload?: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function AudioUploadZone({
  limits,
  phase,
  progress,
  error,
  onFileSelected,
  onCancelUpload,
}: AudioUploadZoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const isBusy = phase !== "idle";
  const acceptAttr = limits.supported_upload_formats
    .map((fmt) => `.${fmt}`)
    .join(",");

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0 || isBusy) return;
    onFileSelected(files[0]);
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!isBusy) setIsDragging(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    handleFiles(event.dataTransfer.files);
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    handleFiles(event.target.files);
  };

  return (
    <section aria-labelledby="upload-heading" className="border border-studio-border bg-studio-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-studio-border px-5 py-3">
        <h2
          id="upload-heading"
          className="text-xs font-semibold uppercase tracking-[0.12em] text-studio-muted"
        >
          Audio Ingestion
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-studio-subtle">
          {limits.supported_upload_formats.map((f) => f.toUpperCase()).join(" / ")} · Max{" "}
          {limits.max_upload_mb} MB · Max {Math.floor(limits.max_duration_seconds / 60)} min
        </span>
      </div>

      <div className="p-5">
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center rounded border border-dashed px-6 py-8 text-center transition-colors ${
            isDragging
              ? "border-studio-cyan bg-studio-cyan/5"
              : "border-studio-border bg-studio-bg/70 hover:border-studio-subtle"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={acceptAttr}
            onChange={handleInputChange}
            disabled={isBusy}
            aria-label="Select audio recording"
            className="sr-only"
          />

          <p className="text-sm font-medium text-studio-text">
            Drop an instrument recording here or select a local file
          </p>
          <p className="mt-1 text-xs text-studio-muted">
            Validated strictly by file header and codec ({limits.supported_upload_formats.map((f) => f.toUpperCase()).join(", ")}).
            Decoded at native sample rate in 32-bit float.
          </p>

          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              disabled={isBusy}
              onClick={() => inputRef.current?.click()}
              className="rounded border border-studio-amber/60 bg-studio-amber/15 px-4 py-1.5 text-xs font-medium text-studio-amber transition-colors hover:bg-studio-amber/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Choose Audio File
            </button>

            {phase === "uploading" && onCancelUpload && (
              <button
                type="button"
                onClick={onCancelUpload}
                className="rounded border border-studio-border bg-studio-elevated px-3 py-1.5 text-xs text-studio-muted transition-colors hover:text-studio-text"
              >
                Cancel Upload
              </button>
            )}
          </div>
        </div>

        {/* Real Byte-Transfer Progress & Honest Server Validation Status */}
        {phase === "uploading" && (
          <div className="mt-4" role="status" aria-live="polite">
            <div className="flex items-center justify-between text-xs">
              <span className="text-studio-text">Uploading file bytes...</span>
              <span className="font-mono tabular-nums text-studio-cyan">
                {progress
                  ? `${progress.percent}% (${formatBytes(progress.loadedBytes)} / ${formatBytes(progress.totalBytes)})`
                  : "0%"}
              </span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-studio-bg">
              <div
                className="h-full bg-studio-cyan transition-all duration-150"
                style={{ width: `${progress?.percent ?? 0}%` }}
              />
            </div>
          </div>
        )}

        {phase === "validating" && (
          <div
            role="status"
            aria-live="polite"
            className="mt-4 flex items-center justify-between rounded border border-studio-border bg-studio-bg px-3.5 py-2.5 text-xs"
          >
            <span className="text-studio-text">
              Upload complete — validating header/codec, decoding native-SR float32, and measuring LUFS/peaks...
            </span>
            <span className="font-mono text-[11px] text-studio-amber">
              Server Processing
            </span>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="mt-4 rounded border border-studio-danger/40 bg-studio-danger/10 px-4 py-3 text-xs"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-semibold text-studio-danger">
                Audio ingestion rejected
              </span>
              <span className="font-mono text-[11px] text-studio-danger/90">
                {error.code}
              </span>
            </div>
            <p className="mt-1 text-studio-text/90">{error.message}</p>
          </div>
        )}
      </div>
    </section>
  );
}
