import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  Loader2,
  Mic,
  MicOff,
  Monitor,
  Pause,
  Play,
  RefreshCw,
  Send,
  Square,
  Volume2,
  VolumeX
} from "lucide-react";
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

function groupTrack(group: ChannelGroupName): TrackName {
  return group === "display" ? "screen" : group;
}

function isRecent(value?: string | null): boolean {
  if (!value) {
    return false;
  }
  const parsed = Date.parse(value);
  return !Number.isNaN(parsed) && Date.now() - parsed < 120_000;
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
  const [capturing, setCapturing] = useState(false);
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
    const matching = groupedChannels.display.filter(channel => sourceMatches(channel, shareMode));
    return matching.length ? matching : groupedChannels.display;
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
  const agentConnected = status?.backend?.mcp_status === "connected" && isRecent(agentLastSeen);
  const agentLabel = status?.backend?.mcp_agent ?? "MCP agent";
  const agentState = agentConnected ? "connected" : agentLastSeen ? "idle" : "waiting";
  const backendReady = status?.backend?.ws_status === "connected";
  const sourceHelp = displayChoices.length
    ? shareMode === "screen"
      ? "Pick the monitor to share."
      : "Pick the app window to share."
    : shareMode === "screen"
      ? "Click Choose source to list available screens."
      : "Click Choose source to list available windows. If none appear, open the target app window and refresh.";

  async function refresh() {
    const [nextStatus, nextEvents] = await Promise.all([getStatus(), getEvents(30)]);
    setStatus(nextStatus);
    setEvents(nextEvents.events);
  }

  useEffect(() => {
    void refresh().catch((reason: unknown) => setError(String(reason)));
    const timer = window.setInterval(() => {
      void getStatus()
        .then(setStatus)
        .catch(() => undefined);
    }, 4000);

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
      setError("Backend live socket is unavailable.");
    });

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
      window.clearInterval(timer);
      ws.close();
      unsubscribe?.();
    };
  }, [currentSessionId]);

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

  async function startCapture() {
    setBusy(true);
    setError(null);
    try {
      const { session, available } = await loadSources();
      const displays = available.filter(channel => channel.group === "display");
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

  if (capturing) {
    return (
      <main className="floating-mode">
        <section className="floating-toolbar" aria-label="Active Screen-Aware capture">
          <div className="recording-pill">
            <span className="record-dot" />
            <span>Sharing</span>
          </div>

          <div className="toolbar-buttons">
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

          <form className="toolbar-note" onSubmit={event => void submitNote(event)}>
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

          <button className="toolbar-stop" onClick={() => void stopCapture()} disabled={busy}>
            <Square size={16} />
          </button>
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
        <header className="card-top">
          <div className="window-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="agent-badge" data-state={agentConnected ? "connected" : "waiting"}>
            <span>{agentLabel}</span>
            <strong>{agentState}</strong>
          </div>
        </header>

        <div className="mode-switch" aria-label="Capture mode">
          <button
            className={shareMode === "screen" ? "selected" : ""}
            onClick={() => setShareMode("screen")}
            type="button"
          >
            Full screen
          </button>
          <button
            className={shareMode === "window" ? "selected" : ""}
            onClick={() => setShareMode("window")}
            type="button"
          >
            Window
          </button>
        </div>

        <div className="source-help">{sourceHelp}</div>

        <label className="recorder-row">
          <Monitor size={24} />
          <div>
            <span>Source</span>
            <select value={selectedDisplayId} onChange={event => setSelectedDisplayId(event.target.value)}>
              {displayChoices.length ? (
                displayChoices.map(channel => (
                  <option key={channel.id} value={channel.id}>
                    {friendlyChannel(channel)}
                  </option>
                ))
              ) : (
                <option value="">Choose source first</option>
              )}
            </select>
          </div>
          <ChevronDown size={18} />
        </label>

        {displayChoices.length > 0 && (
          <div className="source-list" aria-label="Available share targets">
            {displayChoices.map(channel => (
              <button
                key={channel.id}
                className={channel.id === selectedDisplayId ? "source-option selected" : "source-option"}
                type="button"
                onClick={() => setSelectedDisplayId(channel.id)}
              >
                <span>{sourceKindLabel(channel)}</span>
                <strong>{friendlyChannel(channel)}</strong>
              </button>
            ))}
          </div>
        )}

        {channels.length > 0 && shareMode === "window" && !hasModeSpecificDisplay && (
          <div className="inline-note">
            Window-specific channels were not returned by the capture SDK. Select the closest source above or use full-screen capture.
          </div>
        )}

        <label className="recorder-row">
          {micEnabled ? <Mic size={24} /> : <MicOff size={24} />}
          <div>
            <span>Microphone</span>
            <select
              disabled={!micEnabled}
              value={selectedMicId}
              onChange={event => setSelectedMicId(event.target.value)}
            >
              {groupedChannels.mic.length ? (
                groupedChannels.mic.map(channel => (
                  <option key={channel.id} value={channel.id}>
                    {friendlyChannel(channel)}
                  </option>
                ))
              ) : (
                <option value="">Default microphone</option>
              )}
            </select>
          </div>
          <button
            className={micEnabled ? "small-toggle on" : "small-toggle"}
            type="button"
            onClick={() => setMicEnabled(value => !value)}
          >
            {micEnabled ? "On" : "Off"}
          </button>
        </label>

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

        <button className="secondary-action" onClick={() => void loadSources()} disabled={loadingSources || busy}>
          {loadingSources ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
          {displayChoices.length ? "Refresh sources" : "Choose source"}
        </button>

        <label className="note-area">
          <span>What should the agent understand?</span>
          <textarea
            value={issueText}
            onChange={event => setIssueText(event.target.value)}
            placeholder="The Flappy page starts, but the canvas is blank after pressing Start."
            rows={3}
          />
        </label>

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

        <button className="start-recording" onClick={() => void startCapture()} disabled={busy}>
          {busy ? <Loader2 className="spin" size={20} /> : <Play size={20} />}
          Start sharing
        </button>

        <footer className="card-status">
          <span>{backendReady ? "Backend ready" : status?.backend?.ws_status ?? "Backend offline"}</span>
          <span>{latestEvent?.text ?? latestEvent?.event ?? "No shared context yet"}</span>
        </footer>
      </section>
    </main>
  );
}
