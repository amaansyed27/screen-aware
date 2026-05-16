import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Loader2,
  Mic,
  MicOff,
  Monitor,
  MonitorUp,
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

const GROUP_LABELS: Record<ChannelGroupName, string> = {
  mic: "Mic",
  display: "Screen",
  system_audio: "System sound"
};

function groupTrack(group: ChannelGroupName): TrackName {
  return group === "display" ? "screen" : group;
}

function eventTime(value?: string): string {
  if (!value) {
    return "--:--";
  }
  return value.includes("T") ? value.slice(11, 16) : value.slice(0, 5);
}

function isRecent(value?: string | null): boolean {
  if (!value) {
    return false;
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return false;
  }
  return Date.now() - parsed < 120_000;
}

function friendlyChannel(channel: PlainChannel): string {
  if (channel.name && channel.name !== "Unknown") {
    return channel.name;
  }
  return channel.id;
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

  const selectedDisplay =
    displayChoices.find(channel => channel.id === selectedDisplayId) ?? displayChoices[0] ?? null;
  const selectedMic =
    groupedChannels.mic.find(channel => channel.id === selectedMicId) ??
    groupedChannels.mic[0] ??
    null;

  const agentLastSeen = status?.backend?.mcp_last_seen ?? null;
  const agentConnected = status?.backend?.mcp_status === "connected" && isRecent(agentLastSeen);
  const agentLabel = status?.backend?.mcp_agent ?? "MCP agent";
  const agentState = agentConnected ? "Connected" : agentLastSeen ? "Idle" : "Waiting";
  const backendReady = status?.backend?.ws_status === "connected";

  const recentSignal = events
    .slice(-5)
    .reverse()
    .filter(event => event.text || event.channel || event.event);

  async function refresh() {
    const [nextStatus, nextEvents] = await Promise.all([getStatus(), getEvents(40)]);
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
        setEvents(previous => [...previous.slice(-59), payload.event]);
      }
    });
    ws.addEventListener("error", () => {
      setError("Backend live socket is unavailable.");
    });

    const unsubscribe = tauriCapture.onEvent((event: CompanionEvent) => {
      setEvents(previous => [
        ...previous.slice(-59),
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
      <main className="compact-shell">
        <section className="recorder-bar" aria-label="Active Screen-Aware capture">
          <div className="recording-lockup">
            <span className="record-dot" />
            <div>
              <strong>Sharing</strong>
              <span>{selectedDisplay ? friendlyChannel(selectedDisplay) : "workspace"}</span>
            </div>
          </div>

          <div className="agent-chip" data-state={agentConnected ? "connected" : "waiting"}>
            <span>{agentLabel}</span>
            <strong>{agentState}</strong>
          </div>

          <div className="compact-controls">
            <button
              className="icon-button"
              title="Pause or resume screen"
              onClick={() => void toggleTrack("display")}
            >
              {pausedTracks.screen ? <Play size={17} /> : <Monitor size={17} />}
            </button>
            <button
              className="icon-button"
              title="Pause or resume microphone"
              onClick={() => void toggleTrack("mic")}
              disabled={!micEnabled}
            >
              {pausedTracks.mic || !micEnabled ? <MicOff size={17} /> : <Mic size={17} />}
            </button>
            <button
              className="icon-button"
              title="Pause or resume system sound"
              onClick={() => void toggleTrack("system_audio")}
              disabled={!systemAudioEnabled}
            >
              {pausedTracks.system_audio || !systemAudioEnabled ? (
                <VolumeX size={17} />
              ) : (
                <Volume2 size={17} />
              )}
            </button>
          </div>

          <form className="note-form" onSubmit={event => void submitNote(event)}>
            <input
              value={noteText}
              onChange={event => setNoteText(event.target.value)}
              placeholder="Tell the agent what to look at..."
              aria-label="Describe the issue for the connected agent"
            />
            <button className="icon-button dark" type="submit" disabled={!noteText.trim()}>
              <Send size={16} />
            </button>
          </form>

          <button className="stop-button" onClick={() => void stopCapture()} disabled={busy}>
            <Square size={16} />
            Stop
          </button>
        </section>

        {error && (
          <div className="compact-error">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}
      </main>
    );
  }

  return (
    <main className="setup-shell">
      <header className="simple-header">
        <div>
          <div className="eyebrow">MCP + VideoDB</div>
          <h1>Share with your coding agent</h1>
        </div>
        <div className="agent-status" data-state={agentConnected ? "connected" : "waiting"}>
          <span>{agentLabel}</span>
          <strong>{agentState}</strong>
        </div>
      </header>

      <section className="setup-grid">
        <div className="share-panel">
          <div className="section-heading">
            <MonitorUp size={18} />
            <span>Workspace source</span>
          </div>

          <div className="source-mode" aria-label="Share source type">
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

          <div className="selector-row">
            <label>
              <span>Source</span>
              <div className="select-wrap">
                <select
                  value={selectedDisplayId}
                  onChange={event => setSelectedDisplayId(event.target.value)}
                >
                  {displayChoices.length ? (
                    displayChoices.map(channel => (
                      <option key={channel.id} value={channel.id}>
                        {friendlyChannel(channel)}
                      </option>
                    ))
                  ) : (
                    <option value="">Choose source to list screens and windows</option>
                  )}
                </select>
                <ChevronDown size={16} />
              </div>
            </label>
            <button onClick={() => void loadSources()} disabled={loadingSources || busy}>
              {loadingSources ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}
              Choose source
            </button>
          </div>

          <div className="audio-row">
            <label className="switch-line">
              <input
                type="checkbox"
                checked={micEnabled}
                onChange={event => setMicEnabled(event.target.checked)}
              />
              <span>Microphone</span>
            </label>

            <label className="switch-line">
              <input
                type="checkbox"
                checked={systemAudioEnabled}
                onChange={event => setSystemAudioEnabled(event.target.checked)}
              />
              <span>System sound</span>
            </label>

            <label className="switch-line muted-line">
              <input
                type="checkbox"
                checked={storeCapture}
                onChange={event => setStoreCapture(event.target.checked)}
              />
              <span>Save searchable context</span>
            </label>
          </div>

          {micEnabled && (
            <label className="mic-select">
              <span>Mic input</span>
              <div className="select-wrap">
                <select value={selectedMicId} onChange={event => setSelectedMicId(event.target.value)}>
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
                <ChevronDown size={16} />
              </div>
            </label>
          )}

          <label className="issue-box">
            <span>What should the agent understand?</span>
            <textarea
              value={issueText}
              onChange={event => setIssueText(event.target.value)}
              placeholder="Example: The Flappy page starts, but the canvas is blank after pressing Start."
              rows={4}
            />
          </label>

          {error && (
            <div className="error-line">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}

          <button className="start-share" onClick={() => void startCapture()} disabled={busy}>
            {busy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
            Start sharing
          </button>
        </div>

        <aside className="context-panel">
          <div className="context-row">
            <span>Backend</span>
            <strong>{backendReady ? "Ready" : status?.backend?.ws_status ?? "Offline"}</strong>
          </div>
          <div className="context-row">
            <span>Agent</span>
            <strong>{agentState}</strong>
          </div>
          <div className="context-row">
            <span>Last tool</span>
            <strong>{status?.backend?.mcp_tool ?? "None"}</strong>
          </div>

          <div className="recent-feed">
            <div className="feed-title">Recent signal</div>
            {recentSignal.length ? (
              recentSignal.map((event, index) => (
                <article key={`${event.ts}-${index}`}>
                  <time>{eventTime(event.ts)}</time>
                  <p>{event.text ?? event.channel ?? event.event}</p>
                </article>
              ))
            ) : (
              <div className="quiet-empty">
                <Check size={16} />
                <span>No shared context yet</span>
              </div>
            )}
          </div>
        </aside>
      </section>
    </main>
  );
}
