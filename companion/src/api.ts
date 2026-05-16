import type { ApiStatus, ScreenAwareEvent, SessionHandshake } from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8787";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
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

export function liveUrl(): string {
  const base = new URL(API_BASE);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = "/api/live";
  return base.toString();
}

