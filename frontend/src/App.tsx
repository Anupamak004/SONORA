import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiClientError,
  deleteSession,
  fetchHealth,
  fetchProcessingResult,
  fetchProfiles,
  fetchSession,
  fetchSessions,
  processSession,
  uploadAudioFile,
  type UploadProgressEvent,
} from "./api/client";
import { NoiseAnalysisPanel } from "./components/analysis/NoiseAnalysisPanel";
import { ProfilePreviewPanel } from "./components/layout/ProfilePreviewPanel";
import { StudioHeader } from "./components/layout/StudioHeader";
import { SystemStatusPanel } from "./components/layout/SystemStatusPanel";
import { AudioComparisonDeck } from "./components/processing/AudioComparisonDeck";
import {
  DEFAULT_PROCESS_SETTINGS,
  ProcessingControlsPanel,
} from "./components/processing/ProcessingControlsPanel";
import { RecentSessionsBar } from "./components/sessions/RecentSessionsBar";
import { AudioMetadataInspector } from "./components/upload/AudioMetadataInspector";
import {
  AudioUploadZone,
  type UploadPhase,
} from "./components/upload/AudioUploadZone";
import { OriginalWaveformPlayer } from "./components/waveform/OriginalWaveformPlayer";
import type {
  HealthResponse,
  InstrumentProfile,
  ProcessRequest,
  ProcessResponse,
  SessionDetail,
  SessionSummary,
} from "./types/api";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [profiles, setProfiles] = useState<InstrumentProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>("general");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Stage 2: Audio ingestion & session playback state
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadProgress, setUploadProgress] =
    useState<UploadProgressEvent | null>(null);
  const [uploadError, setUploadError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null,
  );
  const uploadAbortRef = useRef<AbortController | null>(null);

  // Stage 4: Precision Musical DSP processing & comparison state
  const [processSettings, setProcessSettings] = useState<ProcessRequest>(
    DEFAULT_PROCESS_SETTINGS,
  );
  const [processing, setProcessing] = useState<boolean>(false);
  const [processResult, setProcessResult] = useState<ProcessResponse | null>(
    null,
  );
  const [processError, setProcessError] = useState<{
    code: string;
    message: string;
  } | null>(null);

  const loadSystemState = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [healthData, profilesData, sessionsData] = await Promise.all([
        fetchHealth(signal),
        fetchProfiles(signal),
        fetchSessions(signal),
      ]);
      setHealth(healthData);
      setProfiles(profilesData.profiles);
      setSessions(sessionsData.sessions);
      if (profilesData.profiles.length > 0) {
        setSelectedProfileId((prev) =>
          profilesData.profiles.some((p) => p.id === prev)
            ? prev
            : profilesData.profiles[0].id,
        );
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      if (err instanceof ApiClientError) {
        setError(`${err.code}: ${err.message}`);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unable to reach the local SONORA backend.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadSystemState(controller.signal);
    return () => controller.abort();
  }, [loadSystemState]);

  const refreshSessionsList = useCallback(async () => {
    try {
      const data = await fetchSessions();
      setSessions(data.sessions);
    } catch {
      // Non-fatal; primary error handling already covers connectivity
    }
  }, []);

  const handleFileSelected = useCallback(
    async (file: File) => {
      setUploadError(null);
      setUploadProgress(null);

      if (file.size === 0) {
        setUploadError({
          code: "EMPTY_FILE",
          message: "Selected file is empty (0 bytes).",
        });
        return;
      }

      if (health && file.size > health.limits.max_upload_mb * 1024 * 1024) {
        setUploadError({
          code: "FILE_TOO_LARGE",
          message: `Selected file exceeds the server limit of ${health.limits.max_upload_mb} MB.`,
        });
        return;
      }

      const controller = new AbortController();
      uploadAbortRef.current = controller;
      setUploadPhase("uploading");

      try {
        const created = await uploadAudioFile(file, {
          signal: controller.signal,
          onProgress: (prog) => {
            setUploadProgress(prog);
            if (prog.percent >= 100) {
              setUploadPhase("validating");
            }
          },
        });
        setActiveSession(created);
        setProcessResult(null);
        setProcessError(null);
        await refreshSessionsList();
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setUploadError(null);
        } else if (err instanceof ApiClientError) {
          setUploadError({ code: err.code, message: err.message });
        } else if (err instanceof Error) {
          setUploadError({ code: "UPLOAD_ERROR", message: err.message });
        } else {
          setUploadError({
            code: "UPLOAD_ERROR",
            message: "Unexpected error during audio ingestion.",
          });
        }
      } finally {
        uploadAbortRef.current = null;
        setUploadPhase("idle");
        setUploadProgress(null);
      }
    },
    [health, refreshSessionsList],
  );

  const handleCancelUpload = useCallback(() => {
    uploadAbortRef.current?.abort();
  }, []);

  const handleSelectSession = useCallback(
    async (sessionId: string) => {
      setUploadError(null);
      setProcessError(null);
      try {
        const [detail, existingProcess] = await Promise.all([
          fetchSession(sessionId),
          fetchProcessingResult(sessionId).catch(() => null),
        ]);
        setActiveSession(detail);
        setProcessResult(existingProcess);
        if (existingProcess) {
          setProcessSettings(existingProcess.settings_applied);
        }
      } catch (err) {
        if (err instanceof ApiClientError) {
          setUploadError({ code: err.code, message: err.message });
        }
        await refreshSessionsList();
      }
    },
    [refreshSessionsList],
  );

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      setDeletingSessionId(sessionId);
      try {
        await deleteSession(sessionId);
        if (activeSession?.session_id === sessionId) {
          setActiveSession(null);
          setProcessResult(null);
          setProcessError(null);
        }
        await refreshSessionsList();
      } catch (err) {
        if (err instanceof ApiClientError) {
          setUploadError({ code: err.code, message: err.message });
        }
      } finally {
        setDeletingSessionId(null);
      }
    },
    [activeSession?.session_id, refreshSessionsList],
  );

  const handleProcessAudio = useCallback(async () => {
    if (!activeSession) return;
    setProcessing(true);
    setProcessError(null);
    try {
      const result = await processSession(
        activeSession.session_id,
        processSettings,
      );
      setProcessResult(result);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setProcessError({ code: err.code, message: err.message });
      } else if (err instanceof Error) {
        setProcessError({ code: "PROCESSING_ERROR", message: err.message });
      } else {
        setProcessError({
          code: "PROCESSING_ERROR",
          message: "Unexpected error while processing audio.",
        });
      }
    } finally {
      setProcessing(false);
    }
  }, [activeSession, processSettings]);

  return (
    <div className="min-h-screen bg-studio-bg text-studio-text">
      <StudioHeader
        health={health}
        loading={loading}
        error={error}
        onRefresh={() => void loadSystemState()}
      />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        {error && (
          <div
            role="alert"
            className="border border-studio-danger/40 bg-studio-danger/10 px-5 py-4 text-xs text-studio-danger"
          >
            <p className="font-semibold">Backend connection failed</p>
            <p className="mt-1 font-mono text-[11px] text-studio-text/90">
              {error}
            </p>
            <p className="mt-2 text-studio-muted">
              Verify the FastAPI server is running on{" "}
              <code className="font-mono text-studio-text">
                http://127.0.0.1:8000
              </code>{" "}
              and click Refresh.
            </p>
          </div>
        )}

        {loading && !health && !error && (
          <div className="border border-studio-border bg-studio-surface px-5 py-8 text-center font-mono text-xs text-studio-muted">
            Connecting to local SONORA backend...
          </div>
        )}

        {health && (
          <>
            {/* Stage 2: Audio Upload & Validation */}
            <AudioUploadZone
              limits={health.limits}
              phase={uploadPhase}
              progress={uploadProgress}
              error={uploadError}
              onFileSelected={(file) => void handleFileSelected(file)}
              onCancelUpload={handleCancelUpload}
            />

            {/* Loaded Audio Session Studio: Metadata -> Original Player -> Analysis -> DSP -> A/B Comparison */}
            {activeSession && (
              <section
                aria-label="Loaded audio session"
                className="border border-studio-border bg-studio-surface"
              >
                <AudioMetadataInspector
                  session={activeSession}
                  onDelete={(id) => void handleDeleteSession(id)}
                  deleting={deletingSessionId === activeSession.session_id}
                />
                <OriginalWaveformPlayer session={activeSession} />
                <NoiseAnalysisPanel session={activeSession} />
                <ProcessingControlsPanel
                  settings={processSettings}
                  processing={processing}
                  error={processError}
                  onChange={setProcessSettings}
                  onProcess={() => void handleProcessAudio()}
                />
                {processResult &&
                  processResult.session_id === activeSession.session_id && (
                    <AudioComparisonDeck
                      session={activeSession}
                      result={processResult}
                    />
                  )}
              </section>
            )}

            {/* Stage 2: Recent Temp Sessions */}
            <RecentSessionsBar
              sessions={sessions}
              activeSessionId={activeSession?.session_id ?? null}
              onSelect={(id) => void handleSelectSession(id)}
              onDelete={(id) => void handleDeleteSession(id)}
            />

            {/* Stage 1: System Diagnostics & Configurable Instrument Profiles */}
            <div className="border border-studio-border">
              <SystemStatusPanel health={health} />
              <ProfilePreviewPanel
                profiles={profiles}
                selectedId={selectedProfileId}
                onSelect={setSelectedProfileId}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
