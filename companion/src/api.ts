import type { ApiStatus, ScreenAwareEvent, SessionHandshake } from "./types";

const DEV_API_BASE = "/screen-aware-api";
const PROD_API_BASE = "http://127.0.0.1:8787";

export const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? DEV_API_BASE : PROD_API_BASE);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...init
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export function getStatus(): Promise<ApiStatus> {
  return request<ApiStatus>("/api/status");
}

export function getEvents(limit = 50): Promise<{ events: ScreenAwareEvent[] }> {
  return request<{ events: ScreenAwareEvent[] }>(`/api/events?limit=${limit}`);
}

export function createSession(input: {
  end_user_id: string;
  issue_text?: string;
  metadata?: Record<string, unknown>;
}): Promise<SessionHandshake> {
  return request<SessionHandshake>("/api/sessions", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function postClientEvent(input: {
  session_id: string;
  event: string;
  data?: Record<string, unknown>;
}): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/capture/client-event", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function postWindowCaptureSegment(input: {
  sessionId: string;
  sequence: number;
  sourceLabel: string;
  containsAudio: boolean;
  storeCapture: boolean;
  startedAtMs: number;
  endedAtMs: number;
  blob: Blob;
}): Promise<{ ok: boolean; path: string; bytes: number; queued: boolean }> {
  const body = new FormData();
  body.set("session_id", input.sessionId);
  body.set("sequence", String(input.sequence));
  body.set("source_label", input.sourceLabel);
  body.set("contains_audio", String(input.containsAudio));
  body.set("store_capture", String(input.storeCapture));
  body.set("started_at_ms", String(input.startedAtMs));
  body.set("ended_at_ms", String(input.endedAtMs));
  body.set("segment", input.blob, `window-segment-${String(input.sequence).padStart(4, "0")}.webm`);
  return request<{ ok: boolean; path: string; bytes: number; queued: boolean }>(
    "/api/window-capture/segments",
    {
      method: "POST",
      body
    }
  );
}

export function liveUrl(): string {
  if (API_BASE.startsWith("/")) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/screen-aware-live`;
  }
  const base = new URL(API_BASE);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/api/live";
  return base.toString();
}
