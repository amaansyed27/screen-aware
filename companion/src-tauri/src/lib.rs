use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    path::PathBuf,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, Position, Size, State};
use thiserror::Error;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::{oneshot, Mutex},
    time::timeout,
};
use uuid::Uuid;

const PROTOCOL_PREFIX: &str = "videodb_recorder|";
const COMMAND_TIMEOUT: Duration = Duration::from_secs(90);

#[derive(Debug, Error)]
enum CaptureError {
    #[error("{0}")]
    Message(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Tauri(#[from] tauri::Error),
}

impl Serialize for CaptureError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::ser::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

type CaptureResult<T> = Result<T, CaptureError>;
type PendingSender = oneshot::Sender<Result<Value, String>>;

#[derive(Default)]
struct CaptureState {
    manager: Mutex<Option<BinaryManager>>,
    channels: Mutex<Vec<PlainChannel>>,
    current_session_id: Mutex<Option<String>>,
    session_token: Mutex<Option<String>>,
    api_url: Mutex<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct InitializeCaptureInput {
    client_token: String,
    api_url: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StartCaptureInput {
    session_id: String,
    channel_ids: Vec<String>,
    primary_video_channel_id: Option<String>,
    store: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ChannelGroupName {
    Mic,
    Display,
    SystemAudio,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum SourceKind {
    Screen,
    Window,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PlainChannel {
    id: String,
    name: String,
    #[serde(rename = "type")]
    channel_type: String,
    group: ChannelGroupName,
    source_kind: SourceKind,
    store: bool,
    is_primary: bool,
}

#[derive(Debug, Serialize)]
struct OkResponse {
    ok: bool,
}

#[derive(Debug, Serialize)]
struct StartResponse {
    ok: bool,
    channels: Vec<Value>,
}

#[derive(Clone, Debug, Serialize)]
struct CaptureEvent {
    event: String,
    data: Value,
    ts: String,
}

struct BinaryManager {
    child: Child,
    stdin: ChildStdin,
    pending: Arc<Mutex<HashMap<String, PendingSender>>>,
}

impl BinaryManager {
    async fn start(app: AppHandle, session_token: String, api_url: String) -> CaptureResult<Self> {
        let binary = capture_binary_path()?;
        let mut child = Command::new(&binary)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|err| {
                CaptureError::Message(format!(
                    "Failed to start VideoDB capture binary at {}: {err}",
                    binary.display()
                ))
            })?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| CaptureError::Message("Failed to open capture binary stdin".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| CaptureError::Message("Failed to open capture binary stdout".into()))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| CaptureError::Message("Failed to open capture binary stderr".into()))?;

        let pending = Arc::new(Mutex::new(HashMap::new()));
        spawn_stdout_reader(app.clone(), pending.clone(), stdout);
        spawn_stderr_reader(app.clone(), stderr);

        let mut manager = Self {
            child,
            stdin,
            pending,
        };
        manager
            .send_command(
                "init",
                json!({ "sessionToken": session_token, "apiUrl": api_url }),
            )
            .await?;
        Ok(manager)
    }

    async fn send_command(&mut self, command: &str, params: Value) -> CaptureResult<Value> {
        let command_id = Uuid::new_v4().to_string();
        let payload = json!({
            "command": command,
            "commandId": command_id,
            "params": params
        });
        let line = format!("{PROTOCOL_PREFIX}{payload}\n");
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(command_id.clone(), tx);

        if let Err(err) = self.stdin.write_all(line.as_bytes()).await {
            self.pending.lock().await.remove(&command_id);
            return Err(CaptureError::Io(err));
        }

        match timeout(COMMAND_TIMEOUT, rx).await {
            Ok(Ok(Ok(value))) => Ok(value),
            Ok(Ok(Err(message))) => Err(CaptureError::Message(message)),
            Ok(Err(_)) => Err(CaptureError::Message(format!(
                "Capture binary closed before replying to command `{command}`"
            ))),
            Err(_) => {
                self.pending.lock().await.remove(&command_id);
                Err(CaptureError::Message(format!(
                    "Timed out waiting for VideoDB capture command `{command}`"
                )))
            }
        }
    }

    async fn shutdown(&mut self) {
        let _ = self.send_command("shutdown", json!({})).await;
        let _ = timeout(Duration::from_secs(5), self.child.wait()).await;
        if let Ok(None) = self.child.try_wait() {
            let _ = self.child.kill().await;
        }
    }
}

fn spawn_stdout_reader(
    app: AppHandle,
    pending: Arc<Mutex<HashMap<String, PendingSender>>>,
    stdout: tokio::process::ChildStdout,
) {
    tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            if let Some(payload) = line.strip_prefix(PROTOCOL_PREFIX) {
                match serde_json::from_str::<Value>(payload) {
                    Ok(message) => handle_binary_message(&app, &pending, message).await,
                    Err(err) => emit_capture_event(
                        &app,
                        "binary.parse_error",
                        json!({ "line": line, "message": err.to_string() }),
                    ),
                }
            } else {
                emit_capture_event(&app, "binary.stdout", json!({ "line": line }));
            }
        }
        emit_capture_event(&app, "binary.stdout_closed", json!({}));
    });
}

fn spawn_stderr_reader(app: AppHandle, stderr: tokio::process::ChildStderr) {
    tauri::async_runtime::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            emit_capture_event(&app, "binary.stderr", json!({ "line": line }));
        }
        emit_capture_event(&app, "binary.stderr_closed", json!({}));
    });
}

async fn handle_binary_message(
    app: &AppHandle,
    pending: &Arc<Mutex<HashMap<String, PendingSender>>>,
    message: Value,
) {
    match message.get("type").and_then(Value::as_str) {
        Some("response") => {
            let Some(command_id) = message.get("commandId").and_then(Value::as_str) else {
                emit_capture_event(app, "binary.malformed_response", message);
                return;
            };
            let status = message
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("error");
            let result = message.get("result").cloned().unwrap_or(Value::Null);
            if let Some(sender) = pending.lock().await.remove(command_id) {
                let _ = if status == "success" {
                    sender.send(Ok(result))
                } else {
                    sender.send(Err(result.to_string()))
                };
            }
        }
        Some("event") => {
            let name = message
                .get("event")
                .and_then(Value::as_str)
                .unwrap_or("binary.event");
            let payload = message.get("payload").cloned().unwrap_or(Value::Null);
            emit_capture_event(app, name, payload);
        }
        _ => emit_capture_event(app, "binary.unknown_message", message),
    }
}

fn emit_capture_event(app: &AppHandle, event: &str, data: Value) {
    let _ = app.emit(
        "capture://event",
        CaptureEvent {
            event: event.to_string(),
            data,
            ts: now_isoish(),
        },
    );
}

fn now_isoish() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    format!("{millis}")
}

fn capture_binary_path() -> CaptureResult<PathBuf> {
    let executable = if cfg!(target_os = "windows") {
        "capture.exe"
    } else {
        "capture"
    };

    if let Ok(path) = env::var("VIDEODB_CAPTURE_BINARY") {
        let path = PathBuf::from(path);
        if path.exists() {
            return Ok(path);
        }
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let companion_dir = manifest_dir
        .parent()
        .ok_or_else(|| CaptureError::Message("Cannot resolve companion directory".into()))?;
    let mut candidates = vec![
        companion_dir
            .join("node_modules")
            .join("videodb")
            .join("bin")
            .join(executable),
        manifest_dir.join("bin").join(executable),
    ];

    if let Ok(current_dir) = env::current_dir() {
        candidates.push(
            current_dir
                .join("node_modules")
                .join("videodb")
                .join("bin")
                .join(executable),
        );
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| {
            CaptureError::Message(
                "VideoDB capture binary was not found. Run `npm install` in companion/ or set VIDEODB_CAPTURE_BINARY to the native VideoDB capture binary path.".into(),
            )
        })
}

async fn ensure_manager(
    app: AppHandle,
    state: &CaptureState,
    input: Option<InitializeCaptureInput>,
) -> CaptureResult<()> {
    let mut manager_guard = state.manager.lock().await;
    if manager_guard.is_some() {
        if let Some(ref input) = input {
            let token = state.session_token.lock().await.clone();
            if token.as_deref() != Some(input.client_token.as_str()) {
                let mut existing = manager_guard.take().expect("manager exists");
                existing.shutdown().await;
                *state.current_session_id.lock().await = None;
            } else {
                return Ok(());
            }
        } else {
            return Ok(());
        }
    }

    let Some(input) = input else {
        return Err(CaptureError::Message(
            "Capture client is not initialized. Create a VideoDB session first.".into(),
        ));
    };
    let api_url = input
        .api_url
        .unwrap_or_else(|| "https://api.videodb.io".to_string());
    let manager = BinaryManager::start(app, input.client_token.clone(), api_url.clone()).await?;
    *state.session_token.lock().await = Some(input.client_token);
    *state.api_url.lock().await = api_url;
    *manager_guard = Some(manager);
    Ok(())
}

#[tauri::command]
async fn initialize_capture(
    app: AppHandle,
    state: State<'_, CaptureState>,
    input: InitializeCaptureInput,
) -> CaptureResult<OkResponse> {
    ensure_manager(app, &state, Some(input)).await?;
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn request_permission(
    app: AppHandle,
    state: State<'_, CaptureState>,
    permission: String,
) -> CaptureResult<String> {
    ensure_manager(app.clone(), &state, None).await?;
    let mut guard = state.manager.lock().await;
    let manager = guard
        .as_mut()
        .ok_or_else(|| CaptureError::Message("Capture client is not initialized.".into()))?;
    let result = manager
        .send_command("requestPermission", json!({ "permission": permission }))
        .await?;
    if result.get("requested").and_then(Value::as_bool) == Some(true) {
        return Ok("granted".into());
    }
    Ok(result
        .get("status")
        .or_else(|| result.get("permission_status"))
        .and_then(Value::as_str)
        .unwrap_or("undetermined")
        .to_string())
}

#[tauri::command]
async fn list_channels(
    app: AppHandle,
    state: State<'_, CaptureState>,
) -> CaptureResult<Vec<PlainChannel>> {
    ensure_manager(app.clone(), &state, None).await?;
    let mut guard = state.manager.lock().await;
    let manager = guard
        .as_mut()
        .ok_or_else(|| CaptureError::Message("Capture client is not initialized.".into()))?;
    let result = manager.send_command("getChannels", json!({})).await?;
    let raw_channels = result
        .get("channels")
        .and_then(Value::as_array)
        .ok_or_else(|| CaptureError::Message("Capture binary returned no channels array".into()))?;
    let channels = raw_channels
        .iter()
        .map(plain_channel_from_value)
        .collect::<Vec<_>>();
    *state.channels.lock().await = channels.clone();
    Ok(channels)
}

fn plain_channel_from_value(value: &Value) -> PlainChannel {
    let id = value
        .get("channel_id")
        .or_else(|| value.get("channelId"))
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let channel_type = value
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("audio")
        .to_string();
    let name = value
        .get("name")
        .or_else(|| value.get("channel_name"))
        .and_then(Value::as_str)
        .unwrap_or("Unknown")
        .to_string();
    let id_lower = id.to_lowercase();
    let name_lower = name.to_lowercase();
    let group = if id_lower.starts_with("display") || channel_type == "video" {
        ChannelGroupName::Display
    } else if id_lower.starts_with("system_audio") {
        ChannelGroupName::SystemAudio
    } else {
        ChannelGroupName::Mic
    };
    let source_kind = if matches!(group, ChannelGroupName::Display)
        && (id_lower.contains("window") || name_lower.contains("window"))
    {
        SourceKind::Window
    } else if matches!(group, ChannelGroupName::Display)
        && (id_lower.contains("display")
            || id_lower.contains("screen")
            || name_lower.contains("display")
            || name_lower.contains("screen")
            || name_lower.contains("monitor"))
    {
        SourceKind::Screen
    } else {
        SourceKind::Unknown
    };
    PlainChannel {
        id,
        name,
        channel_type,
        group,
        source_kind,
        store: true,
        is_primary: false,
    }
}

#[tauri::command]
async fn start_capture(
    app: AppHandle,
    state: State<'_, CaptureState>,
    input: StartCaptureInput,
) -> CaptureResult<StartResponse> {
    ensure_manager(app.clone(), &state, None).await?;
    if input.session_id.trim().is_empty() {
        return Err(CaptureError::Message("sessionId is required".into()));
    }
    if input.channel_ids.is_empty() {
        return Err(CaptureError::Message(
            "At least one channel must be selected".into(),
        ));
    }

    let channels = state.channels.lock().await.clone();
    let selected = channels
        .iter()
        .filter(|channel| input.channel_ids.contains(&channel.id))
        .map(|channel| {
            json!({
                "channel_id": channel.id,
                "type": channel.channel_type,
                "store": input.store,
                "is_primary": input.primary_video_channel_id.as_deref() == Some(channel.id.as_str())
            })
        })
        .collect::<Vec<_>>();
    if selected.is_empty() {
        return Err(CaptureError::Message(
            "Selected channel IDs were not found. Refresh channels and retry.".into(),
        ));
    }
    let primary_video = selected
        .iter()
        .find(|channel| {
            channel.get("is_primary").and_then(Value::as_bool) == Some(true)
                && channel.get("type").and_then(Value::as_str) == Some("video")
        })
        .or_else(|| {
            selected
                .iter()
                .find(|channel| channel.get("type").and_then(Value::as_str) == Some("video"))
        })
        .and_then(|channel| channel.get("channel_id"))
        .and_then(Value::as_str)
        .map(str::to_string);

    let token = state
        .session_token
        .lock()
        .await
        .clone()
        .ok_or_else(|| CaptureError::Message("Missing VideoDB client token".into()))?;

    let mut params = json!({
        "uploadToken": token,
        "sessionId": input.session_id,
        "channels": selected
    });
    if let Some(primary_video) = primary_video {
        params["primary_video_channel_id"] = Value::String(primary_video);
    }

    let mut guard = state.manager.lock().await;
    let manager = guard
        .as_mut()
        .ok_or_else(|| CaptureError::Message("Capture client is not initialized.".into()))?;
    manager.send_command("startRecording", params).await?;
    *state.current_session_id.lock().await = Some(input.session_id.clone());
    emit_capture_event(
        &app,
        "capture.started",
        json!({ "sessionId": input.session_id, "channels": selected }),
    );
    Ok(StartResponse {
        ok: true,
        channels: selected,
    })
}

#[tauri::command]
async fn pause_tracks(
    app: AppHandle,
    state: State<'_, CaptureState>,
    tracks: Vec<String>,
) -> CaptureResult<OkResponse> {
    track_command(app, state, "pauseTracks", tracks, "tracks.paused").await
}

#[tauri::command]
async fn resume_tracks(
    app: AppHandle,
    state: State<'_, CaptureState>,
    tracks: Vec<String>,
) -> CaptureResult<OkResponse> {
    track_command(app, state, "resumeTracks", tracks, "tracks.resumed").await
}

async fn track_command(
    app: AppHandle,
    state: State<'_, CaptureState>,
    command: &str,
    tracks: Vec<String>,
    event: &str,
) -> CaptureResult<OkResponse> {
    ensure_manager(app.clone(), &state, None).await?;
    if tracks.is_empty() {
        return Err(CaptureError::Message("tracks cannot be empty".into()));
    }
    let mut guard = state.manager.lock().await;
    let manager = guard
        .as_mut()
        .ok_or_else(|| CaptureError::Message("Capture client is not initialized.".into()))?;
    manager
        .send_command(command, json!({ "tracks": tracks }))
        .await?;
    emit_capture_event(&app, event, json!({ "tracks": tracks }));
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn stop_capture(app: AppHandle, state: State<'_, CaptureState>) -> CaptureResult<OkResponse> {
    ensure_manager(app.clone(), &state, None).await?;
    let session_id = state
        .current_session_id
        .lock()
        .await
        .clone()
        .unwrap_or_else(|| "current".to_string());
    let mut guard = state.manager.lock().await;
    let manager = guard
        .as_mut()
        .ok_or_else(|| CaptureError::Message("Capture client is not initialized.".into()))?;
    manager
        .send_command("stopRecording", json!({ "sessionId": session_id }))
        .await?;
    *state.current_session_id.lock().await = None;
    emit_capture_event(&app, "capture.stopped", json!({}));
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn shutdown_capture(state: State<'_, CaptureState>) -> CaptureResult<OkResponse> {
    if let Some(mut manager) = state.manager.lock().await.take() {
        manager.shutdown().await;
    }
    *state.current_session_id.lock().await = None;
    *state.session_token.lock().await = None;
    *state.channels.lock().await = Vec::new();
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn set_compact_window(app: AppHandle, compact: bool) -> CaptureResult<OkResponse> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| CaptureError::Message("Main window was not found".into()))?;
    if compact {
        window.set_always_on_top(true)?;
        window.set_size(Size::Logical(LogicalSize {
            width: 940.0,
            height: 190.0,
        }))?;
        if let Some(monitor) = window.current_monitor()? {
            let monitor_size = monitor.size();
            let scale = monitor.scale_factor();
            let logical_width = monitor_size.width as f64 / scale;
            let x = ((logical_width - 940.0) / 2.0).max(24.0);
            window.set_position(Position::Logical(LogicalPosition { x, y: 24.0 }))?;
        }
    } else {
        window.set_always_on_top(false)?;
        window.set_size(Size::Logical(LogicalSize {
            width: 440.0,
            height: 660.0,
        }))?;
    }
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn set_overlay_collapsed(app: AppHandle, collapsed: bool) -> CaptureResult<OkResponse> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| CaptureError::Message("Main window was not found".into()))?;
    window.set_always_on_top(true)?;
    let (width, height) = if collapsed {
        (360.0, 94.0)
    } else {
        (940.0, 190.0)
    };
    window.set_size(Size::Logical(LogicalSize { width, height }))?;
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn window_control(app: AppHandle, action: String) -> CaptureResult<OkResponse> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| CaptureError::Message("Main window was not found".into()))?;
    match action.as_str() {
        "minimize" => window.minimize()?,
        "close" => window.close()?,
        _ => {
            return Err(CaptureError::Message(format!(
                "Unknown window control action `{action}`"
            )))
        }
    }
    Ok(OkResponse { ok: true })
}

#[tauri::command]
async fn window_start_dragging(app: AppHandle) -> CaptureResult<OkResponse> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| CaptureError::Message("Main window was not found".into()))?;
    window.start_dragging()?;
    Ok(OkResponse { ok: true })
}

pub fn run() {
    tauri::Builder::default()
        .manage(CaptureState::default())
        .invoke_handler(tauri::generate_handler![
            initialize_capture,
            request_permission,
            list_channels,
            start_capture,
            pause_tracks,
            resume_tracks,
            stop_capture,
            shutdown_capture,
            set_compact_window,
            set_overlay_collapsed,
            window_control,
            window_start_dragging
        ])
        .setup(|app| {
            let _ = app.path().app_data_dir();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Screen-Aware companion");
}
