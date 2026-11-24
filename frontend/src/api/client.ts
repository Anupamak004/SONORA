import type {
  AnalysisRequest,
  AnalysisResponse,
  ApiErrorEnvelope,
  HealthResponse,
  ProcessRequest,
  ProcessResponse,
  ProfilesResponse,
  SessionDetail,
  SessionsListResponse,
} from "../types/api";

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(
    message: string,
    code: string,
    status: number,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function getBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL;
  return typeof configured === "string" ? configured.replace(/\/+$/, "") : "";
}

async function requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Request failed with status ${response.status}`;
    let details: Record<string, unknown> | undefined;

    try {
      const payload = (await response.json()) as Partial<ApiErrorEnvelope>;
      if (payload.error?.message) {
        message = payload.error.message;
      }
      if (payload.error?.code) {
        code = payload.error.code;
      }
      details = payload.error?.details;
    } catch {
      // Fall back to HTTP status text when response body is not JSON
    }

    throw new ApiClientError(message, code, response.status, details);
  }

  return (await response.json()) as T;
}

export function resolveApiUrl(path: string): string {
  return `${getBaseUrl()}${path}`;
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health", signal);
}

export function fetchProfiles(signal?: AbortSignal): Promise<ProfilesResponse> {
  return requestJson<ProfilesResponse>("/api/v1/profiles", signal);
}

export function fetchSessions(
  signal?: AbortSignal,
): Promise<SessionsListResponse> {
  return requestJson<SessionsListResponse>("/api/v1/sessions", signal);
}

export function fetchSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SessionDetail> {
  return requestJson<SessionDetail>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
    signal,
  );
}

export async function analyzeSession(
  sessionId: string,
  params: AnalysisRequest = {},
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  const url = resolveApiUrl(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/analyze`,
  );
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(params),
    signal,
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Analysis failed with status ${response.status}`;
    let details: Record<string, unknown> | undefined;
    try {
      const payload = (await response.json()) as Partial<ApiErrorEnvelope>;
      if (payload.error?.code) code = payload.error.code;
      if (payload.error?.message) message = payload.error.message;
      details = payload.error?.details;
    } catch {
      // Fallback to HTTP status message
    }
    throw new ApiClientError(message, code, response.status, details);
  }

  return (await response.json()) as AnalysisResponse;
}

export async function processSession(
  sessionId: string,
  request: Partial<ProcessRequest>,
  signal?: AbortSignal,
): Promise<ProcessResponse> {
  const url = resolveApiUrl(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/process`,
  );
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Processing failed with status ${response.status}`;
    let details: Record<string, unknown> | undefined;
    try {
      const payload = (await response.json()) as Partial<ApiErrorEnvelope>;
      if (payload.error?.code) code = payload.error.code;
      if (payload.error?.message) message = payload.error.message;
      details = payload.error?.details;
    } catch {
      // Fallback to HTTP status message
    }
    throw new ApiClientError(message, code, response.status, details);
  }

  return (await response.json()) as ProcessResponse;
}

export async function fetchProcessingResult(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ProcessResponse | null> {
  const url = resolveApiUrl(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/process`,
  );
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new ApiClientError(
      `Failed to load processing status (${response.status})`,
      `HTTP_${response.status}`,
      response.status,
    );
  }
  return (await response.json()) as ProcessResponse;
}

export async function deleteSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<void> {
  const url = resolveApiUrl(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
  const response = await fetch(url, {
    method: "DELETE",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Failed to delete session (status ${response.status})`;
    try {
      const payload = (await response.json()) as Partial<ApiErrorEnvelope>;
      if (payload.error?.code) code = payload.error.code;
      if (payload.error?.message) message = payload.error.message;
    } catch {
      // Ignore parse errors on non-JSON failure bodies
    }
    throw new ApiClientError(message, code, response.status);
  }
}

export interface UploadProgressEvent {
  loadedBytes: number;
  totalBytes: number;
  percent: number;
}

export interface UploadOptions {
  onProgress?: (progress: UploadProgressEvent) => void;
  signal?: AbortSignal;
}

/**
 * Upload an audio file using XMLHttpRequest to expose real byte transfer progress.
 */
export function uploadAudioFile(
  file: File,
  options: UploadOptions = {},
): Promise<SessionDetail> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);

    const handleAbort = () => {
      xhr.abort();
      reject(new DOMException("Upload canceled", "AbortError"));
    };

    if (options.signal) {
      if (options.signal.aborted) {
        reject(new DOMException("Upload canceled", "AbortError"));
        return;
      }
      options.signal.addEventListener("abort", handleAbort, { once: true });
    }

    const cleanup = () => {
      options.signal?.removeEventListener("abort", handleAbort);
    };

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && options.onProgress) {
        const percent = Math.min(
          100,
          Math.max(0, Math.round((event.loaded / event.total) * 100)),
        );
        options.onProgress({
          loadedBytes: event.loaded,
          totalBytes: event.total,
          percent,
        });
      }
    });

    xhr.addEventListener("load", () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as SessionDetail);
        } catch {
          reject(
            new ApiClientError(
              "Server returned unreadable session metadata.",
              "INVALID_RESPONSE",
              xhr.status,
            ),
          );
        }
        return;
      }

      let code = `HTTP_${xhr.status}`;
      let message = `Upload failed with status ${xhr.status}`;
      let details: Record<string, unknown> | undefined;
      try {
        const parsed = JSON.parse(xhr.responseText) as Partial<ApiErrorEnvelope>;
        if (parsed.error?.code) code = parsed.error.code;
        if (parsed.error?.message) message = parsed.error.message;
        details = parsed.error?.details;
      } catch {
        // Use HTTP fallback message
      }
      reject(new ApiClientError(message, code, xhr.status, details));
    });

    xhr.addEventListener("error", () => {
      cleanup();
      reject(
        new ApiClientError(
          "Network error occurred while uploading audio to local backend.",
          "NETWORK_ERROR",
          0,
        ),
      );
    });

    xhr.open("POST", resolveApiUrl("/api/v1/sessions/upload"));
    xhr.setRequestHeader("Accept", "application/json");
    xhr.send(formData);
  });
}
