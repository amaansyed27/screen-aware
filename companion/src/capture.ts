import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type { CaptureBridge, CompanionEvent, PlainChannel, TrackName } from "./types";

export const tauriCapture: CaptureBridge = {
  initialize(input: { clientToken: string; apiUrl?: string }) {
    return invoke<{ ok: boolean }>("initialize_capture", { input });
  },
  requestPermission(permission: "microphone" | "screen-capture") {
    return invoke<string>("request_permission", { permission });
  },
  listChannels() {
    return invoke<PlainChannel[]>("list_channels");
  },
  start(input: {
    sessionId: string;
    channelIds: string[];
    primaryVideoChannelId?: string;
    store: boolean;
  }) {
    return invoke<{ ok: boolean; channels: unknown[] }>("start_capture", { input });
  },
  pauseTracks(tracks: TrackName[]) {
    return invoke<{ ok: boolean }>("pause_tracks", { tracks });
  },
  resumeTracks(tracks: TrackName[]) {
    return invoke<{ ok: boolean }>("resume_tracks", { tracks });
  },
  stop() {
    return invoke<{ ok: boolean }>("stop_capture");
  },
  shutdown() {
    return invoke<{ ok: boolean }>("shutdown_capture");
  },
  onEvent(callback: (event: CompanionEvent) => void) {
    let active = true;
    let unlisten: (() => void) | null = null;
    void listen<CompanionEvent>("capture://event", event => callback(event.payload)).then(dispose => {
      if (active) {
        unlisten = dispose;
      } else {
        dispose();
      }
    });
    return () => {
      active = false;
      unlisten?.();
    };
  }
};

