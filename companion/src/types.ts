export type ChannelGroupName = "mic" | "display" | "system_audio";
export type TrackName = "mic" | "screen" | "system_audio";

export interface PlainChannel {
  id: string;
  name: string;
  type: "audio" | "video";
  group: ChannelGroupName;
  source_kind?: "screen" | "window" | "unknown";
  store: boolean;
  is_primary: boolean;
}

export interface CaptureBridge {
  initialize(input: { clientToken: string; apiUrl?: string }): Promise<{ ok: boolean }>;
  requestPermission(permission: "microphone" | "screen-capture"): Promise<string>;
  listChannels(): Promise<PlainChannel[]>;
  start(input: {
    sessionId: string;
    channelIds: string[];
    primaryVideoChannelId?: string;
    store: boolean;
  }): Promise<{ ok: boolean; channels: unknown[] }>;
  pauseTracks(tracks: TrackName[]): Promise<{ ok: boolean }>;
  resumeTracks(tracks: TrackName[]): Promise<{ ok: boolean }>;
  stop(): Promise<{ ok: boolean }>;
  shutdown(): Promise<{ ok: boolean }>;
  setCompactWindow(compact: boolean): Promise<{ ok: boolean }>;
  onEvent(callback: (event: CompanionEvent) => void): () => void;
}

export interface CompanionEvent {
  event: string;
  data?: Record<string, unknown>;
  ts?: string;
}

export interface SessionHandshake {
  session_id: string;
  client_token: string;
  token_ttl_seconds: number;
  collection_id: string;
  videodb_api_url?: string;
}

export interface ScreenAwareEvent {
  ts?: string;
  channel?: string;
  event?: string;
  capture_session_id?: string;
  rtstream_id?: string;
  rtstream_name?: string;
  text?: string;
  data?: unknown;
}

export interface ApiStatus {
  backend: {
    ws_connection_id?: string;
    ws_status?: string;
    last_error?: string | null;
    mcp_status?: string;
    mcp_agent?: string | null;
    mcp_last_seen?: string | null;
    mcp_tool?: string | null;
  };
  current_session_id?: string | null;
  session?: Record<string, unknown> | null;
}
