import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  AudioLines,
  Circle,
  Loader2,
  Mic,
  MonitorUp,
  Pause,
  Play,
  RefreshCw,
  Square,
  Terminal
} from "lucide-react";
import {
  createSession,
  getEvents,
  getStatus,
  liveUrl,
  postClientEvent
} from "./api";
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

const GROUP_LABELS: Record<ChannelGroupName, string> = {
  mic: "Mic",
  display: "Screen",
  system_audio: "System"
};

function groupTrack(group: ChannelGroupName): TrackName {
  if (group === "display") {
    return "screen";
  }
  return group;
}

function shortToken(token: string | null): string {
  if (!token) {
    return "not issued";
  }
  if (token.length <= 12) {
    return token;
  }
  return `${token.slice(0, 6)}...${token.slice(-6)}`;
}

export default function App() {
  const [status, setStatus] = useState<ApiStatus | null>(null);
  const [events, setEvents] = useState<ScreenAwareEvent[]>([]);
  const [channels, setChannels] = useState<PlainChannel[]>([]);
  const [handshake, setHandshake] = useState<SessionHandshake | null>(null);
  const [issueText, setIssueText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [storeCapture, setStoreCapture] = useState(true);
  const [selectedGroups, setSelectedGroups] = useState<Record<ChannelGroupName, boolean>>({
    mic: true,
    display: true,
    system_audio: false
  });
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

  async function refresh() {
    const [nextStatus, nextEvents] = await Promise.all([getStatus(), getEvents(50)]);
    setStatus(nextStatus);
    setEvents(nextEvents.events);
  }

  useEffect(() => {
    void refresh().catch((reason: unknown) => setError(String(reason)));

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
      ws.close();
      unsubscribe?.();
    };
  }, [currentSessionId]);

  async function prepareSession(): Promise<SessionHandshake> {
    const result = await createSession({
      end_user_id: "local-developer",
      issue_text: issueText || undefined,
      metadata: {
        companion: "tauri-react",
        capture_groups: selectedGroups
      }
    });
    setHandshake(result);
    return result;
  }

  async function startCapture() {
    setBusy(true);
    setError(null);
    try {
      const session = await prepareSession();
      await tauriCapture.initialize({
        clientToken: session.client_token,
        apiUrl: session.videodb_api_url
      });

      if (selectedGroups.mic || selectedGroups.system_audio) {
        await tauriCapture.requestPermission("microphone");
      }
      if (selectedGroups.display) {
        await tauriCapture.requestPermission("screen-capture");
      }

      const available = await tauriCapture.listChannels();
      setChannels(available);

      const selected = available.filter(channel => selectedGroups[channel.group]);
      const primaryDisplay = selected.find(channel => channel.group === "display");
      await tauriCapture.start({
        sessionId: session.session_id,
        channelIds: selected.map(channel => channel.id),
        primaryVideoChannelId: primaryDisplay?.id,
        store: storeCapture
      });
      setCapturing(true);
      await postClientEvent({
        session_id: session.session_id,
        event: "capture.started",
        data: { channel_ids: selected.map(channel => channel.id), store: storeCapture }
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

  const recentSignal = events
    .slice(-8)
    .reverse()
    .filter(event => event.text || event.channel || event.event);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">MCP + VideoDB</div>
          <h1>Screen-Aware</h1>
        </div>
        <div className="status-strip" aria-label="Runtime status">
          <span className={status?.backend?.ws_status === "connected" ? "dot dot-on" : "dot"} />
          <span>{status?.backend?.ws_status ?? "offline"}</span>
          <code>{status?.backend?.ws_connection_id ?? "no-ws"}</code>
        </div>
      </header>

      <section className="grid">
        <div className="panel control-panel">
          <div className="panel-title">
            <Terminal size={18} />
            <span>Control</span>
          </div>

          <label className="field">
            <span>Issue</span>
            <textarea
              value={issueText}
              onChange={event => setIssueText(event.target.value)}
              placeholder="Paste or type the bug context."
              rows={5}
              disabled={capturing}
            />
          </label>

          <div className="toggles" aria-label="Capture toggles">
            <label className="toggle">
              <input
                type="checkbox"
                checked={selectedGroups.display}
                disabled={capturing}
                onChange={event =>
                  setSelectedGroups(previous => ({ ...previous, display: event.target.checked }))
                }
              />
              <MonitorUp size={18} />
              <span>Screen</span>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={selectedGroups.mic}
                disabled={capturing}
                onChange={event =>
                  setSelectedGroups(previous => ({ ...previous, mic: event.target.checked }))
                }
              />
              <Mic size={18} />
              <span>Mic</span>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={selectedGroups.system_audio}
                disabled={capturing}
                onChange={event =>
                  setSelectedGroups(previous => ({
                    ...previous,
                    system_audio: event.target.checked
                  }))
                }
              />
              <AudioLines size={18} />
              <span>System</span>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={storeCapture}
                disabled={capturing}
                onChange={event => setStoreCapture(event.target.checked)}
              />
              <Circle size={18} />
              <span>Store</span>
            </label>
          </div>

          <div className="button-row">
            <button className="primary" onClick={() => void startCapture()} disabled={busy || capturing}>
              {busy && !capturing ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              <span>Start</span>
            </button>
            <button onClick={() => void stopCapture()} disabled={busy || !capturing}>
              <Square size={18} />
              <span>Stop</span>
            </button>
            <button onClick={() => void refresh()} disabled={busy}>
              <RefreshCw size={18} />
              <span>Refresh</span>
            </button>
          </div>

          {capturing && (
            <div className="button-row compact">
              {(["display", "mic", "system_audio"] as ChannelGroupName[]).map(group => (
                <button key={group} onClick={() => void toggleTrack(group)}>
                  {pausedTracks[groupTrack(group)] ? <Play size={16} /> : <Pause size={16} />}
                  <span>{GROUP_LABELS[group]}</span>
                </button>
              ))}
            </div>
          )}

          {error && (
            <div className="warning">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}
        </div>

        <div className="panel session-panel">
          <div className="panel-title">
            <MonitorUp size={18} />
            <span>Session</span>
          </div>
          <dl className="kv">
            <div>
              <dt>ID</dt>
              <dd>{currentSessionId ?? "none"}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{String(status?.session?.status ?? "idle")}</dd>
            </div>
            <div>
              <dt>Client</dt>
              <dd>{String(status?.session?.client_status ?? (capturing ? "capturing" : "idle"))}</dd>
            </div>
            <div>
              <dt>Token</dt>
              <dd>{shortToken(handshake?.client_token ?? null)}</dd>
            </div>
          </dl>

          <div className="channel-list">
            {(["display", "mic", "system_audio"] as ChannelGroupName[]).map(group => (
              <div className="channel-group" key={group}>
                <div className="channel-heading">{GROUP_LABELS[group]}</div>
                {groupedChannels[group].length ? (
                  groupedChannels[group].map(channel => (
                    <code key={channel.id}>{channel.id}</code>
                  ))
                ) : (
                  <span className="muted">not listed</span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="panel live-panel">
          <div className="panel-title">
            <AudioLines size={18} />
            <span>Live Context</span>
          </div>
          <div className="event-list">
            {recentSignal.length ? (
              recentSignal.map((event, index) => (
                <article className="event-row" key={`${event.ts}-${index}`}>
                  <div className="event-meta">
                    <span>{event.channel ?? event.event ?? "event"}</span>
                    <time>{event.ts?.slice(11, 19) ?? "--:--:--"}</time>
                  </div>
                  <p>{event.text ?? JSON.stringify(event.data ?? {})}</p>
                </article>
              ))
            ) : (
              <div className="empty">No signal yet.</div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
