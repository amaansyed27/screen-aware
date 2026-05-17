import { FormEvent, MouseEvent as ReactMouseEvent, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Mic,
  MicOff,
  Minus,
  Monitor,
  Pause,
  Play,
  RefreshCw,
  Send,
  Square,
  X,
  Volume2,
  VolumeX
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { createSession, getEvents, getStatus, liveUrl, postClientEvent } from "./api";
import { tauriCapture } from "./capture";
import type {
  ApiStatus,
  ChannelGroupName,
  CompanionEvent,
  PlainChannel,
  ScreenAwareEvent,
  SessionHandshake,
  TrackName
} from "./types";

type ShareMode = "screen" | "window";
type MenuName = "source" | "mic" | null;

interface NativeSourceSelection {
  label: string;
  displaySurface?: string;
}

function groupTrack(group: ChannelGroupName): TrackName {
  return group === "display" ? "screen" : group;
}

function displayAgentName(value?: string | null): string {
  const normalized = value?.trim();
  return normalized || "Coding agent";
}

function compactAgentName(value: string): string {
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= 16) {
    return clean;
  }
  return `${clean.slice(0, 15).trim()}...`;
}

function friendlyChannel(channel?: PlainChannel | null): string {
  if (!channel) {
    return "Choose source";
  }
  if (channel.name && channel.name !== "Unknown") {
    return channel.name;
  }
  return channel.id;
}

function sourceKindLabel(channel: PlainChannel): string {
  if (channel.source_kind === "window") {
    return "Window";
  }
  if (channel.source_kind === "screen") {
    return "Full screen";
  }
  return "Source";
}

function sourceMatches(channel: PlainChannel, mode: ShareMode): boolean {
  if (channel.source_kind === mode) {
    return true;
  }
  if (!channel.source_kind || channel.source_kind === "unknown") {
    return mode === "screen";
  }
  return false;
}

function channelSignature(items: PlainChannel[]): string {
  return items.map(channel => `${channel.group}:${channel.id}`).sort().join("|");
}

function rawChannelToPlain(value: unknown): PlainChannel | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const id =
    typeof record.channel_id === "string"
      ? record.channel_id
      : typeof record.channelId === "string"
        ? record.channelId
        : typeof record.id === "string"
          ? record.id
          : "";
  if (!id) {
    return null;
  }
  const type = record.type === "video" ? "video" : "audio";
  const name =
    typeof record.name === "string"
      ? record.name
      : typeof record.channel_name === "string"
        ? record.channel_name
        : id;
  const idLower = id.toLowerCase();
  const nameLower = name.toLowerCase();
  const group: ChannelGroupName =
    idLower.startsWith("system_audio")
      ? "system_audio"
      : idLower.startsWith("display") || type === "video"
        ? "display"
        : "mic";
  const source_kind: PlainChannel["source_kind"] =
    group !== "display"
      ? "unknown"
      : idLower.includes("window") || nameLower.includes("window")
        ? "window"
        : idLower.includes("display") ||
            idLower.includes("screen") ||
            nameLower.includes("display") ||
            nameLower.includes("screen") ||
            nameLower.includes("monitor")
          ? "screen"
          : "unknown";
  return {
    id,
    name,
    type,
    group,
    source_kind,
    store: true,
    is_primary: false
  };
}

function channelsFromPayload(payload: unknown): PlainChannel[] {
  if (!payload || typeof payload !== "object") {
    return [];
  }
  const channels = (payload as Record<string, unknown>).channels;
  if (!Array.isArray(channels)) {
    return [];
  }
  return channels.map(rawChannelToPlain).filter((channel): channel is PlainChannel => Boolean(channel));
}

function channelsFromStatus(status: ApiStatus | null): PlainChannel[] {
  const session = status?.session;
  const clientEvents = session?.client_events;
  if (!Array.isArray(clientEvents)) {
    return [];
  }
  for (const event of [...clientEvents].reverse()) {
    if (!event || typeof event !== "object") {
      continue;
    }
    const record = event as Record<string, unknown>;
    if (record.event === "channel-list") {
      return channelsFromPayload(record.data);
    }
  }
  return [];
}

function channelsFromEvents(events: ScreenAwareEvent[]): PlainChannel[] {
  for (const event of [...events].reverse()) {
    if (event.event === "channel-list") {
      return channelsFromPayload(event.data);
    }
  }
  return [];
}

function isCameraLike(channel: PlainChannel): boolean {
  const value = `${channel.id} ${channel.name}`.toLowerCase();
  return value.includes("camera") || value.includes("webcam");
}

export default function App() {
  const [status, setStatus] = useState<ApiStatus | null>(null);
  const [events, setEvents] = useState<ScreenAwareEvent[]>([]);
  const [channels, setChannels] = useState<PlainChannel[]>([]);
  const [handshake, setHandshake] = useState<SessionHandshake | null>(null);
  const [issueText, setIssueText] = useState("");
  const [noteText, setNoteText] = useState("");
  const [shareMode, setShareMode] = useState<ShareMode>("screen");
  const [selectedDisplayId, setSelectedDisplayId] = useState("");
  const [selectedMicId, setSelectedMicId] = useState("");
  const [micEnabled, setMicEnabled] = useState(true);
  const [systemAudioEnabled, setSystemAudioEnabled] = useState(false);
  const [storeCapture, setStoreCapture] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadingSources, setLoadingSources] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [overlayCollapsed, setOverlayCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState<MenuName>(null);
  const [nativeSource, setNativeSource] = useState<NativeSourceSelection | null>(null);
  const [pausedTracks, setPausedTracks] = useState<Record<TrackName, boolean>>({
    mic: false,
    screen: false,
    system_audio: false
  });

  const currentSessionId = handshake?.session_id ?? status?.current_session_id ?? null;

  const groupedChannels = useMemo(() => {
    return channels.reduce<Record<ChannelGroupName, PlainChannel[]>>(
      (acc, channel) => {
        acc[channel.group].push(channel);
        return acc;
      },
      { mic: [], display: [], system_audio: [] }
    );
  }, [channels]);

  const displayChoices = useMemo(() => {
    const shareableDisplays = groupedChannels.display.filter(channel => !isCameraLike(channel));
    if (shareMode === "window") {
      return shareableDisplays.filter(channel => sourceMatches(channel, "window"));
    }
    const matching = shareableDisplays.filter(channel => sourceMatches(channel, shareMode));
    return matching.length ? matching : shareableDisplays;
  }, [groupedChannels.display, shareMode]);
  const hasModeSpecificDisplay = groupedChannels.display.some(channel =>
    sourceMatches(channel, shareMode)
  );

  const selectedDisplay =
    displayChoices.find(channel => channel.id === selectedDisplayId) ?? displayChoices[0] ?? null;
  const selectedMic =
    groupedChannels.mic.find(channel => channel.id === selectedMicId) ??
    groupedChannels.mic[0] ??
    null;
  const latestEvent = events
    .slice()
    .reverse()
    .find(event => event.text || event.channel || event.event);

  const agentLastSeen = status?.backend?.mcp_last_seen ?? null;
  const mcpStatus = status?.backend?.mcp_status ?? "waiting";
  const agentConnected = mcpStatus === "connected";
  const agentLinked = agentConnected || Boolean(agentLastSeen) || Boolean(status?.backend?.mcp_agent);
  const agentLabel = displayAgentName(status?.backend?.mcp_agent);
  const agentState = agentConnected ? "Connected" : agentLinked ? "Idle" : "Waiting";
  const agentBadgeState = agentConnected ? "connected" : agentLinked ? "idle" : "waiting";
  const shareSubtitle = agentLabel === "Coding agent" ? "Share with your agent" : `Share with ${agentLabel}`;
  const backendReady = status?.backend?.ws_status === "connected";
  const sourceHelp = displayChoices.length
    ? shareMode === "screen"
      ? "Pick the monitor to share."
      : "Pick the app window to share."
    : shareMode === "screen"
      ? "Click Choose source to list available screens."
      : "Use the native picker to choose a window, like a video call.";
  const sourceLabel =
    shareMode === "window"
      ? nativeSource?.label ?? "Choose window"
      : loadingSources
        ? "Looking for sources..."
        : friendlyChannel(selectedDisplay);
  const windowCaptureBlocked = shareMode === "window";

  async function refresh() {
    const [nextStatus, nextEvents] = await Promise.all([getStatus(), getEvents(30)]);
    setStatus(nextStatus);
    setEvents(nextEvents.events);
    setBackendOnline(true);
  }

  useEffect(() => {
    let stopped = false;

    async function poll() {
      try {
        await refresh();
        if (!stopped) {
          setError(null);
        }
      } catch {
        if (!stopped) {
          setBackendOnline(false);
          setError("Backend unavailable. Start screen-aware-api, then refresh.");
        }
      }
    }

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, backendOnline ? 6000 : 12000);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [backendOnline]);

  useEffect(() => {
    if (!backendOnline) {
      return undefined;
    }
    const ws = new WebSocket(liveUrl());
    ws.addEventListener("message", message => {
      const payload = JSON.parse(String(message.data));
      if (payload.type === "status") {
        setStatus(payload.state);
      }
      if (payload.type === "events") {
        setEvents(payload.events);
      }
      if (payload.type === "videodb_event") {
        setEvents(previous => [...previous.slice(-39), payload.event]);
      }
    });
    ws.addEventListener("error", () => {
      setBackendOnline(false);
      setError("Backend live socket is unavailable. Restart screen-aware-api.");
    });
    ws.addEventListener("close", () => {
      setBackendOnline(false);
    });

    return () => {
      ws.close();
    };
  }, [backendOnline]);

  useEffect(() => {
    const unsubscribe = tauriCapture.onEvent((event: CompanionEvent) => {
      setEvents(previous => [
        ...previous.slice(-39),
        {
          ts: event.ts,
          event: event.event,
          text: typeof event.data?.message === "string" ? event.data.message : undefined,
          data: event.data
        }
      ]);
      if (currentSessionId) {
        void postClientEvent({
          session_id: currentSessionId,
          event: event.event,
          data: event.data
        }).catch(() => undefined);
      }
    });

    return () => {
      unsubscribe?.();
    };
  }, [currentSessionId]);

  useEffect(() => {
    const savedChannels = channelsFromStatus(status);
    if (savedChannels.length && channelSignature(savedChannels) !== channelSignature(channels)) {
      setChannels(savedChannels);
    }
  }, [channels, status]);

  useEffect(() => {
    const savedChannels = channelsFromEvents(events);
    if (savedChannels.length && channelSignature(savedChannels) !== channelSignature(channels)) {
      setChannels(savedChannels);
    }
  }, [channels, events]);

  useEffect(() => {
    if (selectedDisplayId && displayChoices.some(channel => channel.id === selectedDisplayId)) {
      return;
    }
    setSelectedDisplayId(displayChoices[0]?.id ?? "");
  }, [displayChoices, selectedDisplayId]);

  useEffect(() => {
    if (selectedMicId && groupedChannels.mic.some(channel => channel.id === selectedMicId)) {
      return;
    }
    setSelectedMicId(groupedChannels.mic[0]?.id ?? "");
  }, [groupedChannels.mic, selectedMicId]);

  async function prepareSession(): Promise<SessionHandshake> {
    if (handshake) {
      return handshake;
    }
    const result = await createSession({
      end_user_id: "local-developer",
      issue_text: issueText || undefined,
      metadata: {
        companion: "tauri-react",
        share_mode: shareMode,
        mic_enabled: micEnabled,
        system_audio_enabled: systemAudioEnabled
      }
    });
    setHandshake(result);
    return result;
  }

  async function loadSources(): Promise<{ session: SessionHandshake; available: PlainChannel[] }> {
    setLoadingSources(true);
    setError(null);
    try {
      const session = await prepareSession();
      await tauriCapture.initialize({
        clientToken: session.client_token,
        apiUrl: session.videodb_api_url
      });
      await tauriCapture.requestPermission("screen-capture");
      if (micEnabled || systemAudioEnabled) {
        await tauriCapture.requestPermission("microphone");
      }
      const available = await tauriCapture.listChannels();
      setChannels(available);
      return { session, available };
    } finally {
      setLoadingSources(false);
    }
  }

  async function handleLoadSources(menuToOpen: MenuName = "source") {
    try {
      const { available } = await loadSources();
      const shareableDisplays = available.filter(
        channel => channel.group === "display" && !isCameraLike(channel)
      );
      if (menuToOpen) {
        setOpenMenu(menuToOpen);
      }
      if (!shareableDisplays.length) {
        setError("No screen or window sources were returned. Check screen capture permission and retry.");
      }
    } catch (reason) {
      setOpenMenu(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function pickNativeSource() {
    setError(null);
    setOpenMenu(null);
    if (!navigator.mediaDevices?.getDisplayMedia) {
      setError("Native window picker is not available in this WebView. Use Full screen capture.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: "window"
        },
        audio: false
      });
      const [track] = stream.getVideoTracks();
      const settings = track?.getSettings?.() ?? {};
      const label = track?.label?.trim() || "Selected window";
      setNativeSource({
        label,
        displaySurface: typeof settings.displaySurface === "string" ? settings.displaySurface : undefined
      });
      stream.getTracks().forEach(item => item.stop());
      setError("Window selected with the native picker. VideoDB capture SDK currently streams display channels only; use Full screen to stream to VideoDB.");
    } catch (reason) {
      setNativeSource(null);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function openSourcePicker() {
    if (shareMode === "window") {
      await pickNativeSource();
      return;
    }
    if (displayChoices.length) {
      setOpenMenu(openMenu === "source" ? null : "source");
      return;
    }
    await handleLoadSources("source");
  }

  async function openMicPicker() {
    if (groupedChannels.mic.length) {
      setOpenMenu(openMenu === "mic" ? null : "mic");
      return;
    }
    await handleLoadSources("mic");
  }

  async function startCapture() {
    setBusy(true);
    setError(null);
    try {
      if (shareMode === "window") {
        throw new Error(
          "Window-specific streaming is not exposed by the installed VideoDB capture SDK. Use Full screen to stream to VideoDB, or keep Window mode only as a native picker preview."
        );
      }
      const { session, available } = await loadSources();
      const displays = available.filter(channel => channel.group === "display" && !isCameraLike(channel));
      const matchingDisplays = displays.filter(channel => sourceMatches(channel, shareMode));
      const display =
        matchingDisplays.find(channel => channel.id === selectedDisplayId) ??
        displays.find(channel => channel.id === selectedDisplayId) ??
        matchingDisplays[0] ??
        displays[0];
      if (!display) {
        throw new Error("No screen or window source is available. Choose source and grant access.");
      }

      const selectedIds = [display.id];
      const mic = available.find(channel => channel.id === selectedMicId) ?? selectedMic;
      const system = available.find(channel => channel.group === "system_audio");
      if (micEnabled && mic) {
        selectedIds.push(mic.id);
      }
      if (systemAudioEnabled && system) {
        selectedIds.push(system.id);
      }

      await tauriCapture.start({
        sessionId: session.session_id,
        channelIds: selectedIds,
        primaryVideoChannelId: display.id,
        store: storeCapture
      });
      setCapturing(true);
      setOverlayCollapsed(false);
      await tauriCapture.setCompactWindow(true).catch(() => undefined);
      await postClientEvent({
        session_id: session.session_id,
        event: "capture.started",
        data: {
          channel_ids: selectedIds,
          share_mode: shareMode,
          display: display.name,
          mic: micEnabled ? mic?.name : null,
          system_audio: systemAudioEnabled,
          store: storeCapture
        }
      });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function stopCapture() {
    setBusy(true);
    setError(null);
    try {
      await tauriCapture.stop();
      if (currentSessionId) {
        await postClientEvent({
          session_id: currentSessionId,
          event: "capture.stopped",
          data: {}
        });
      }
      setCapturing(false);
      setOverlayCollapsed(false);
      await tauriCapture.setCompactWindow(false).catch(() => undefined);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function toggleTrack(group: ChannelGroupName) {
    const track = groupTrack(group);
    const paused = pausedTracks[track];
    try {
      if (paused) {
        await tauriCapture.resumeTracks([track]);
      } else {
        await tauriCapture.pauseTracks([track]);
      }
      setPausedTracks(previous => ({ ...previous, [track]: !paused }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  async function submitNote(event: FormEvent) {
    event.preventDefault();
    const text = noteText.trim();
    if (!text || !currentSessionId) {
      return;
    }
    setNoteText("");
    await postClientEvent({
      session_id: currentSessionId,
      event: "user.note",
      data: { text }
    });
    await refresh();
  }

  async function windowControl(action: "minimize" | "close") {
    await invoke("window_control", { action });
  }

  async function setCollapsed(nextCollapsed: boolean) {
    setOverlayCollapsed(nextCollapsed);
    await invoke("set_overlay_collapsed", { collapsed: nextCollapsed });
  }

  function selectSource(channelId: string) {
    setSelectedDisplayId(channelId);
    setOpenMenu(null);
  }

  function selectMic(channelId: string) {
    setSelectedMicId(channelId);
    setOpenMenu(null);
  }

  async function beginWindowDrag(event: ReactMouseEvent<HTMLElement>) {
    if (event.button !== 0) {
      return;
    }
    const target = event.target as HTMLElement;
    if (target.closest("button, input, textarea, [data-no-drag='true']")) {
      return;
    }
    await invoke("window_start_dragging");
  }

  if (capturing) {
    return (
      <main className="floating-mode">
        <section
          className={overlayCollapsed ? "floating-toolbar collapsed" : "floating-toolbar"}
          aria-label="Active Screen-Aware capture"
          onMouseDown={event => void beginWindowDrag(event)}
        >
          <div className="recording-pill">
            <span className="record-dot" />
            <span>Sharing</span>
          </div>

          {!overlayCollapsed && (
            <>
              <div className="toolbar-buttons" data-no-drag="true">
                <button title="Pause or resume screen" onClick={() => void toggleTrack("display")}>
                  {pausedTracks.screen ? <Play size={18} /> : <Monitor size={18} />}
                </button>
                <button
                  title="Pause or resume microphone"
                  onClick={() => void toggleTrack("mic")}
                  disabled={!micEnabled}
                >
                  {pausedTracks.mic || !micEnabled ? <MicOff size={18} /> : <Mic size={18} />}
                </button>
                <button
                  title="Pause or resume system sound"
                  onClick={() => void toggleTrack("system_audio")}
                  disabled={!systemAudioEnabled}
                >
                  {pausedTracks.system_audio || !systemAudioEnabled ? (
                    <VolumeX size={18} />
                  ) : (
                    <Volume2 size={18} />
                  )}
                </button>
              </div>

              <form className="toolbar-note" data-no-drag="true" onSubmit={event => void submitNote(event)}>
                <input
                  value={noteText}
                  onChange={event => setNoteText(event.target.value)}
                  placeholder="Describe what the agent should inspect..."
                  aria-label="Describe what the agent should inspect"
                />
                <button type="submit" disabled={!noteText.trim()} title="Send note">
                  <Send size={16} />
                </button>
              </form>
            </>
          )}

          <div className="toolbar-right" data-no-drag="true">
            <button
              className="toolbar-collapse"
              type="button"
              title={overlayCollapsed ? "Expand overlay" : "Collapse overlay"}
              aria-label={overlayCollapsed ? "Expand overlay" : "Collapse overlay"}
              onClick={() => void setCollapsed(!overlayCollapsed)}
            >
              {overlayCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </button>

            <button className="toolbar-stop" onClick={() => void stopCapture()} disabled={busy}>
              <Square size={16} />
            </button>
          </div>
        </section>
        {error && (
          <div className="floating-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}
      </main>
    );
  }

  return (
    <main className="recorder-stage">
      <section className="recorder-card" aria-label="Screen-Aware recorder">
        <header className="card-top" onMouseDown={event => void beginWindowDrag(event)}>
          <div className="app-mark">
            <span className="app-logo-shell" aria-hidden="true">
              <img className="app-logo" src="/logo-192.png" alt="" />
            </span>
            <div>
              <strong>Screen-Aware</strong>
              <small>{shareSubtitle}</small>
            </div>
          </div>
          <div className="header-actions" data-no-drag="true">
            <div
              className="agent-badge"
              data-state={agentBadgeState}
              title={`${agentLabel}: ${agentState}`}
            >
              <span className="agent-dot" aria-hidden="true" />
              <span className="agent-copy">
                <strong>{compactAgentName(agentLabel)}</strong>
                <small>{agentState}</small>
              </span>
            </div>
            <div className="window-controls" aria-label="Window controls">
              <button
                type="button"
                aria-label="Minimize"
                title="Minimize"
                onClick={() => void windowControl("minimize")}
              >
                <Minus size={15} />
              </button>
              <button
                type="button"
                aria-label="Close"
                title="Close"
                onClick={() => void windowControl("close")}
              >
                <X size={15} />
              </button>
            </div>
          </div>
        </header>

        <div className="mode-switch" aria-label="Capture mode">
          <button
            className={shareMode === "screen" ? "selected" : ""}
            onClick={() => {
              setShareMode("screen");
              setOpenMenu(null);
            }}
            type="button"
          >
            Full screen
          </button>
          <button
            className={shareMode === "window" ? "selected" : ""}
            onClick={() => {
              setShareMode("window");
              setOpenMenu(null);
            }}
            type="button"
          >
            Window
          </button>
        </div>

        <div className="source-help">{sourceHelp}</div>

        <div className="recorder-row picker-row" data-no-drag="true">
          <Monitor size={24} />
          <div>
            <span>Source</span>
            <button
              className="picker-value"
              type="button"
              onClick={() => void openSourcePicker()}
            >
              {sourceLabel}
            </button>
          </div>
          <button
            className="picker-chevron"
            type="button"
            aria-label="Open source menu"
            onClick={() => void openSourcePicker()}
          >
            {loadingSources ? <Loader2 className="spin" size={18} /> : <ChevronDown size={18} />}
          </button>
          {openMenu === "source" && (
            <div className={displayChoices.length ? "picker-menu" : "picker-menu empty"} role="menu">
              {displayChoices.length ? (
                displayChoices.map(channel => (
                  <button
                    key={channel.id}
                    className={channel.id === selectedDisplayId ? "picker-option selected" : "picker-option"}
                    type="button"
                    role="menuitem"
                    onClick={() => selectSource(channel.id)}
                  >
                    <span>{sourceKindLabel(channel)}</span>
                    <strong>{friendlyChannel(channel)}</strong>
                  </button>
                ))
              ) : (
                <div className="picker-empty">
                  {loadingSources ? "Looking for screens and windows..." : "No sources listed yet. Click Refresh sources."}
                </div>
              )}
            </div>
          )}
        </div>

        {channels.length > 0 && shareMode === "window" && !hasModeSpecificDisplay && (
          <div className="inline-note">
            Native window picking is available, but the installed VideoDB capture SDK exposes display channels only. Use Full screen to stream into VideoDB.
          </div>
        )}

        <div className="recorder-row picker-row" data-no-drag="true">
          {micEnabled ? <Mic size={24} /> : <MicOff size={24} />}
          <div>
            <span>Microphone</span>
            <button
              className="picker-value"
              disabled={!micEnabled}
              type="button"
              onClick={() => void openMicPicker()}
            >
              {selectedMic ? friendlyChannel(selectedMic) : "Default microphone"}
            </button>
          </div>
          <button
            className={micEnabled ? "small-toggle on" : "small-toggle"}
            type="button"
            onClick={() => {
              setMicEnabled(value => !value);
              setOpenMenu(null);
            }}
          >
            {micEnabled ? "On" : "Off"}
          </button>
          {openMenu === "mic" && micEnabled && (
            <div className={groupedChannels.mic.length ? "picker-menu" : "picker-menu empty"} role="menu">
              {groupedChannels.mic.length ? (
                groupedChannels.mic.map(channel => (
                  <button
                    key={channel.id}
                    className={channel.id === selectedMicId ? "picker-option selected" : "picker-option"}
                    type="button"
                    role="menuitem"
                    onClick={() => selectMic(channel.id)}
                  >
                    <span>Microphone</span>
                    <strong>{friendlyChannel(channel)}</strong>
                  </button>
                ))
              ) : (
                <div className="picker-empty">Default microphone</div>
              )}
            </div>
          )}
        </div>

        <div className="recorder-row">
          {systemAudioEnabled ? <Volume2 size={24} /> : <VolumeX size={24} />}
          <div>
            <span>System sound</span>
            <strong>{systemAudioEnabled ? "Included" : "Not shared"}</strong>
          </div>
          <button
            className={systemAudioEnabled ? "small-toggle on" : "small-toggle"}
            type="button"
            onClick={() => setSystemAudioEnabled(value => !value)}
          >
            {systemAudioEnabled ? "On" : "Off"}
          </button>
        </div>

        <button
          className="secondary-action"
          onClick={() => void (shareMode === "window" ? pickNativeSource() : handleLoadSources("source"))}
          disabled={loadingSources || busy}
        >
          {loadingSources ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
          {shareMode === "window" ? "Choose window" : displayChoices.length ? "Refresh sources" : "Choose source"}
        </button>

        <label className="save-context">
          <input
            type="checkbox"
            checked={storeCapture}
            onChange={event => setStoreCapture(event.target.checked)}
          />
          <span>Save searchable context</span>
        </label>

        {error && (
          <div className="inline-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        <button className="start-recording" onClick={() => void startCapture()} disabled={busy || windowCaptureBlocked}>
          {busy ? <Loader2 className="spin" size={20} /> : <Play size={20} />}
          {shareMode === "window" ? "Use full screen to share" : "Start sharing"}
        </button>

        <footer className="card-status">
          <span>{backendReady ? "Backend ready" : status?.backend?.ws_status ?? "Backend offline"}</span>
          <span>{latestEvent?.text ?? latestEvent?.event ?? "No shared context yet"}</span>
        </footer>
      </section>
    </main>
  );
}
