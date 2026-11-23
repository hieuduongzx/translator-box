use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use futures_util::{SinkExt, StreamExt};
use once_cell::sync::Lazy;
use parking_lot::Mutex;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::HeaderValue;
use tokio_tungstenite::tungstenite::Message;

pub const SONIOX_WEBSOCKET_URL: &str = "wss://stt-rt.soniox.com/transcribe-websocket";
pub const SONIOX_MODEL: &str = "stt-rt-v6";
pub const SONIOX_CLIENT_REFERENCE: &str = "translator2k";

const KEEPALIVE_IDLE_SECS: f64 = 8.0;
const FINALIZE_AFTER_SILENCE_SECS: f64 = 1.5;
const STANDBY_AFTER_SILENCE_SECS: f64 = 20.0;
const SILENCE_PEAK: f32 = 0.002;
const STANDBY_PREROLL_BYTES: usize = 96_000;
const MAX_WAKE_BUFFER_BYTES: usize = 1_048_576;
const MAX_ENDPOINT_DELAY_MS: u32 = 1_200;

static TRANSLATION_TERM_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s*(?:=>|→)\s*").unwrap());
static CONTEXT_SPLIT_RE: Lazy<Regex> = Lazy::new(|| Regex::new(r"[,;\n\r]+").unwrap());

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDeviceOption {
    pub label: String,
    pub id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TranscriptBlock {
    pub kind: String,
    pub text: String,
    pub language: Option<String>,
    pub speaker: Option<String>,
    pub is_final: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SonioxStatePayload {
    pub state: String,
    pub source: String,
    pub error: Option<String>,
    pub blocks: Vec<TranscriptBlock>,
}

#[derive(Debug, Clone)]
pub struct SonioxStartParams {
    pub api_key: String,
    pub audio_source: String,
    pub device_id: String,
    pub system_device: String,
    pub translation_mode: String,
    pub target_language: String,
    pub language_a: String,
    pub language_b: String,
    pub speaker_diarization: bool,
    pub context_text: String,
    pub context_terms: String,
}

#[derive(Default)]
struct TranscriptBuffer {
    final_blocks: Vec<TranscriptBlock>,
    final_speaker: Option<String>,
    non_final_tokens: Vec<Value>,
}

impl TranscriptBuffer {
    fn ingest(&mut self, tokens: &[Value]) {
        let mut non_final = Vec::new();
        for token in tokens {
            let text = token.get("text").and_then(Value::as_str).unwrap_or("");
            if text.is_empty() || text.trim() == "<end>" {
                continue;
            }
            if token.get("is_final").and_then(Value::as_bool).unwrap_or(false) {
                Self::append_token(&mut self.final_blocks, token, &mut self.final_speaker);
            } else {
                non_final.push(token.clone());
            }
        }
        self.non_final_tokens = non_final;
    }

    fn append_token(
        blocks: &mut Vec<TranscriptBlock>,
        token: &Value,
        speaker: &mut Option<String>,
    ) {
        let text = token.get("text").and_then(Value::as_str).unwrap_or("");
        if text.is_empty() {
            return;
        }
        if let Some(sp) = token.get("speaker") {
            if let Some(s) = sp.as_str() {
                *speaker = Some(s.to_string());
            } else if let Some(n) = sp.as_i64() {
                *speaker = Some(n.to_string());
            }
        }
        let kind = if token
            .get("translation_status")
            .and_then(Value::as_str)
            == Some("translation")
        {
            "translation"
        } else {
            "speech"
        };
        let language = token
            .get("language")
            .or_else(|| token.get("source_language"))
            .and_then(Value::as_str)
            .map(String::from);
        let is_final = token
            .get("is_final")
            .and_then(Value::as_bool)
            .unwrap_or(false);

        if let Some(last) = blocks.last_mut() {
            if last.kind == kind && last.language == language && last.speaker == *speaker {
                last.text.push_str(text);
                last.is_final = last.is_final && is_final;
                return;
            }
        }
        blocks.push(TranscriptBlock {
            kind: kind.to_string(),
            text: text.trim_start().to_string(),
            language,
            speaker: speaker.clone(),
            is_final,
        });
    }

    fn blocks(&self) -> Vec<TranscriptBlock> {
        let mut out = self.final_blocks.clone();
        let mut sp = self.final_speaker.clone();
        for tok in &self.non_final_tokens {
            Self::append_token(&mut out, tok, &mut sp);
        }
        out.into_iter().filter(|b| !b.text.trim().is_empty()).collect()
    }
}

fn build_context(context_text: &str, context_terms: &str) -> Option<Value> {
    let mut ctx = serde_json::Map::new();
    let txt: String = context_text.trim().chars().take(4000).collect();
    if !txt.is_empty() {
        ctx.insert("text".into(), json!(txt));
    }
    let mut terms: Vec<String> = Vec::new();
    let mut seen_terms: HashSet<String> = HashSet::new();
    let mut translation_terms: Vec<Value> = Vec::new();

    let raw_terms: String = context_terms.chars().take(2000).collect();
    for part in CONTEXT_SPLIT_RE.split(&raw_terms) {
        let cleaned: String = part
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .chars()
            .take(80)
            .collect();
        if cleaned.is_empty() {
            continue;
        }
        let split: Vec<&str> = TRANSLATION_TERM_RE.splitn(&cleaned, 2).collect();
        if split.len() == 2 && !split[0].is_empty() && !split[1].is_empty() {
            let (s, t) = (split[0].to_string(), split[1].to_string());
            translation_terms.push(json!({ "source": s, "target": t }));
            if seen_terms.insert(s.to_lowercase()) && terms.len() < 200 {
                terms.push(s);
            }
        } else if seen_terms.insert(cleaned.to_lowercase()) && terms.len() < 200 {
            terms.push(cleaned);
        }
    }
    if !terms.is_empty() {
        ctx.insert("terms".into(), json!(terms));
    }
    if !translation_terms.is_empty() {
        ctx.insert("translation_terms".into(), json!(translation_terms));
    }
    if ctx.is_empty() {
        None
    } else {
        Some(Value::Object(ctx))
    }
}

fn describe_soniox_error(payload: &Value) -> String {
    let err_type = payload.get("error_type").and_then(Value::as_str).unwrap_or("");
    let detail = payload
        .get("error_message")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    match err_type {
        "unauthenticated" => "Soniox API key không hợp lệ hoặc đã hết hạn.".to_string(),
        "permission_denied" => "API key không có quyền dùng Soniox realtime STT.".to_string(),
        "organization_balance_exhausted" => "Tài khoản Soniox đã hết số dư.".to_string(),
        "organization_monthly_budget_exhausted" => {
            "Tổ chức Soniox đã chạm hạn mức ngân sách tháng.".to_string()
        }
        "limit_exceeded" => "Vượt giới hạn tần suất Soniox; thử lại sau ít phút.".to_string(),
        "max_concurrent_connections_reached" => {
            "Đang có quá nhiều phiên Soniox cùng lúc; thử lại sau ~20 giây.".to_string()
        }
        "max_duration_reached" => "Phiên Soniox đã đạt giới hạn 300 phút.".to_string(),
        "service_unavailable" => "Soniox tạm thời không khả dụng.".to_string(),
        "invalid_request" if !detail.is_empty() => format!("Cấu hình Soniox không hợp lệ: {detail}"),
        _ => format!(
            "Soniox: {}",
            if !detail.is_empty() {
                detail
            } else if !err_type.is_empty() {
                err_type
            } else {
                "lỗi không xác định"
            }
        ),
    }
}

fn pcm_s16le_peak(data: &[u8]) -> f32 {
    let mut max_abs = 0i32;
    for chunk in data.chunks_exact(2) {
        let s = i16::from_le_bytes([chunk[0], chunk[1]]) as i32;
        max_abs = max_abs.max(s.abs());
    }
    max_abs as f32 / 32768.0
}

// ---------------------------------------------------------------------------
// Windows WASAPI Audio Enumeration & Capture (Mic + System Loopback)
// ---------------------------------------------------------------------------

#[cfg(windows)]
pub fn list_audio_devices(is_system_loopback: bool) -> Vec<AudioDeviceOption> {
    use windows::Win32::Devices::FunctionDiscovery::PKEY_Device_FriendlyName;
    use windows::Win32::Media::Audio::{
        eCapture, eRender, IMMDeviceEnumerator, MMDeviceEnumerator, DEVICE_STATE_ACTIVE,
    };
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CoUninitialize, CLSCTX_ALL, COINIT_MULTITHREADED, STGM_READ,
    };

    let mut out = vec![AudioDeviceOption {
        label: if is_system_loopback {
            "Mặc định Windows".to_string()
        } else {
            "Mặc định hệ thống".to_string()
        },
        id: String::new(),
    }];

    unsafe {
        let hr = CoInitializeEx(None, COINIT_MULTITHREADED);
        let did_init = hr.is_ok();
        if let Ok(enumerator) =
            CoCreateInstance::<_, IMMDeviceEnumerator>(&MMDeviceEnumerator, None, CLSCTX_ALL)
        {
            let flow = if is_system_loopback { eRender } else { eCapture };
            if let Ok(collection) = enumerator.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE) {
                let count = collection.GetCount().unwrap_or(0);
                for i in 0..count {
                    if let Ok(dev) = collection.Item(i) {
                        let id = dev
                            .GetId()
                            .ok()
                            .and_then(|p| p.to_string().ok())
                            .unwrap_or_default();
                        let label = dev
                            .OpenPropertyStore(STGM_READ)
                            .ok()
                            .and_then(|store| store.GetValue(&PKEY_Device_FriendlyName).ok())
                            .map(|prop| prop.to_string())
                            .unwrap_or_else(|| "Thiết bị âm thanh".to_string());
                        if !id.is_empty() {
                            out.push(AudioDeviceOption { label, id });
                        }
                    }
                }
            }
        }
        if did_init {
            CoUninitialize();
        }
    }
    out
}

#[cfg(not(windows))]
pub fn list_audio_devices(is_system_loopback: bool) -> Vec<AudioDeviceOption> {
    vec![AudioDeviceOption {
        label: if is_system_loopback {
            "Mặc định Windows".to_string()
        } else {
            "Mặc định hệ thống".to_string()
        },
        id: String::new(),
    }]
}

struct CaptureInfo {
    sample_rate: u32,
    channels: u16,
}

#[cfg(windows)]
fn start_wasapi_capture(
    is_loopback: bool,
    device_id: String,
    stop: Arc<AtomicBool>,
    chunk_tx: mpsc::UnboundedSender<Vec<u8>>,
) -> Result<CaptureInfo, String> {
    use windows::core::PCWSTR;
    use windows::Win32::Media::Audio::{
        eCapture, eConsole, eRender, IAudioCaptureClient, IAudioClient, IMMDeviceEnumerator,
        MMDeviceEnumerator, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
        WAVEFORMATEX, WAVEFORMATEXTENSIBLE,
    };
    use windows::Win32::System::Com::{
        CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_ALL,
        COINIT_MULTITHREADED,
    };

    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<Result<CaptureInfo, String>>();

    std::thread::Builder::new()
        .name("wasapi-capture".into())
        .spawn(move || unsafe {
            let hr = CoInitializeEx(None, COINIT_MULTITHREADED);
            let did_init = hr.is_ok();

            let res: Result<(), String> = (|| {
                let enumerator: IMMDeviceEnumerator =
                    CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)
                        .map_err(|e| format!("Không khởi tạo được WASAPI: {e}"))?;

                let device = if !device_id.is_empty() {
                    let wide: Vec<u16> = device_id.encode_utf16().chain(Some(0)).collect();
                    enumerator
                        .GetDevice(PCWSTR(wide.as_ptr()))
                        .or_else(|_| {
                            enumerator.GetDefaultAudioEndpoint(
                                if is_loopback { eRender } else { eCapture },
                                eConsole,
                            )
                        })
                        .map_err(|e| format!("Không mở được thiết bị âm thanh: {e}"))?
                } else {
                    enumerator
                        .GetDefaultAudioEndpoint(
                            if is_loopback { eRender } else { eCapture },
                            eConsole,
                        )
                        .map_err(|e| format!("Không tìm thấy thiết bị âm thanh mặc định: {e}"))?
                };

                let client: IAudioClient = device
                    .Activate(CLSCTX_ALL, None)
                    .map_err(|e| format!("Không kích hoạt được WASAPI client: {e}"))?;

                let mix_ptr = client
                    .GetMixFormat()
                    .map_err(|e| format!("Không đọc được định dạng âm thanh: {e}"))?;
                let mix: WAVEFORMATEX = *mix_ptr;
                let sample_rate = mix.nSamplesPerSec;
                let channels = mix.nChannels;
                let bits = mix.wBitsPerSample;
                let format_tag = mix.wFormatTag;
                let is_float = if format_tag == 3 {
                    true
                } else if format_tag == 0xFFFE && mix.cbSize >= 22 {
                    let ext = &*(mix_ptr as *const WAVEFORMATEXTENSIBLE);
                    // KSDATAFORMAT_SUBTYPE_IEEE_FLOAT starts with 0x00000003
                    ext.SubFormat.data1 == 3
                } else {
                    false
                };

                let stream_flags = if is_loopback {
                    AUDCLNT_STREAMFLAGS_LOOPBACK
                } else {
                    0
                };
                // 200ms buffer
                let buffer_duration = 2_000_000i64;
                client
                    .Initialize(
                        AUDCLNT_SHAREMODE_SHARED,
                        stream_flags,
                        buffer_duration,
                        0,
                        mix_ptr,
                        None,
                    )
                    .map_err(|e| format!("Khởi tạo luồng WASAPI thất bại: {e}"))?;
                CoTaskMemFree(Some(mix_ptr as *const _));

                let capture_client: IAudioCaptureClient = client
                    .GetService()
                    .map_err(|e| format!("Không lấy được WASAPI CaptureClient: {e}"))?;
                client
                    .Start()
                    .map_err(|e| format!("Không bắt đầu thu âm được: {e}"))?;

                let out_channels = channels.min(2).max(1);
                let _ = ready_tx.send(Ok(CaptureInfo {
                    sample_rate,
                    channels: out_channels,
                }));

                let block_align = (channels as usize) * ((bits as usize) / 8);
                while !stop.load(Ordering::Relaxed) {
                    std::thread::sleep(Duration::from_millis(20));
                    loop {
                        let pkt_frames = capture_client.GetNextPacketSize().unwrap_or(0);
                        if pkt_frames == 0 {
                            break;
                        }
                        let mut data_ptr: *mut u8 = std::ptr::null_mut();
                        let mut num_frames = 0u32;
                        let mut flags = 0u32;
                        if capture_client
                            .GetBuffer(&mut data_ptr, &mut num_frames, &mut flags, None, None)
                            .is_err()
                        {
                            break;
                        }
                        let frames = num_frames as usize;
                        if frames > 0 && !data_ptr.is_null() {
                            let is_silent = (flags & 0x2) != 0; // AUDCLNT_BUFFERFLAGS_SILENT
                            let mut pcm16 = Vec::with_capacity(frames * out_channels as usize * 2);
                            if is_silent {
                                pcm16.resize(frames * out_channels as usize * 2, 0);
                            } else {
                                let raw = std::slice::from_raw_parts(data_ptr, frames * block_align);
                                for f in 0..frames {
                                    for ch in 0..out_channels as usize {
                                        let off = f * block_align + ch * ((bits as usize) / 8);
                                        let sample_i16 = if is_float && bits == 32 && off + 4 <= raw.len() {
                                            let v = f32::from_le_bytes([
                                                raw[off],
                                                raw[off + 1],
                                                raw[off + 2],
                                                raw[off + 3],
                                            ]);
                                            (v.clamp(-1.0, 1.0) * 32767.0).round() as i16
                                        } else if bits == 16 && off + 2 <= raw.len() {
                                            i16::from_le_bytes([raw[off], raw[off + 1]])
                                        } else if bits == 32 && off + 4 <= raw.len() {
                                            let v = i32::from_le_bytes([
                                                raw[off],
                                                raw[off + 1],
                                                raw[off + 2],
                                                raw[off + 3],
                                            ]);
                                            (v >> 16) as i16
                                        } else {
                                            0
                                        };
                                        pcm16.extend_from_slice(&sample_i16.to_le_bytes());
                                    }
                                }
                            }
                            let _ = chunk_tx.send(pcm16);
                        }
                        let _ = capture_client.ReleaseBuffer(num_frames);
                    }
                }
                let _ = client.Stop();
                Ok(())
            })();

            if let Err(err) = res {
                let _ = ready_tx.send(Err(err));
            }
            if did_init {
                CoUninitialize();
            }
        })
        .map_err(|e| format!("Không tạo được luồng thu âm: {e}"))?;

    ready_rx
        .recv_timeout(Duration::from_secs(5))
        .map_err(|_| "Quá thời gian chờ mở thiết bị âm thanh.".to_string())?
}

#[cfg(not(windows))]
fn start_wasapi_capture(
    _is_loopback: bool,
    _device_id: String,
    _stop: Arc<AtomicBool>,
    _chunk_tx: mpsc::UnboundedSender<Vec<u8>>,
) -> Result<CaptureInfo, String> {
    Err("Thu âm WASAPI chỉ hỗ trợ Windows.".to_string())
}

// ---------------------------------------------------------------------------
// Soniox Session Manager
// ---------------------------------------------------------------------------

pub struct SonioxManager {
    stop_flag: Arc<Mutex<Option<Arc<AtomicBool>>>>,
    state: Arc<Mutex<SonioxStatePayload>>,
}

impl SonioxManager {
    pub fn new() -> Self {
        Self {
            stop_flag: Arc::new(Mutex::new(None)),
            state: Arc::new(Mutex::new(SonioxStatePayload {
                state: "idle".to_string(),
                source: "system".to_string(),
                error: None,
                blocks: Vec::new(),
            })),
        }
    }

    pub fn snapshot(&self) -> SonioxStatePayload {
        self.state.lock().clone()
    }

    pub fn stop(&self) {
        if let Some(flag) = self.stop_flag.lock().take() {
            flag.store(true, Ordering::Relaxed);
        }
    }

    pub fn clear_transcript(&self) {
        self.state.lock().blocks.clear();
    }

    pub fn start<F>(&self, params: SonioxStartParams, on_update: F) -> Result<(), String>
    where
        F: Fn(SonioxStatePayload) + Send + Sync + 'static,
    {
        if self.stop_flag.lock().is_some() {
            return Err("Phiên dịch Audio đang chạy.".to_string());
        }
        let key = params.api_key.trim().to_string();
        if key.is_empty() {
            return Err("Chưa nhập Soniox API key.".to_string());
        }
        if key.contains('\r') || key.contains('\n') {
            return Err("Soniox API key chứa ký tự không hợp lệ.".to_string());
        }

        let is_loopback = params.audio_source == "system";
        let dev_id = if is_loopback {
            params.system_device.clone()
        } else {
            params.device_id.clone()
        };

        let stop = Arc::new(AtomicBool::new(false));
        let (chunk_tx, mut chunk_rx) = mpsc::unbounded_channel::<Vec<u8>>();
        let capture_info = start_wasapi_capture(is_loopback, dev_id, stop.clone(), chunk_tx)?;

        *self.stop_flag.lock() = Some(stop.clone());
        let state_arc = self.state.clone();
        let on_update = Arc::new(on_update);

        let emit = {
            let state_arc = state_arc.clone();
            let on_update = on_update.clone();
            let source = params.audio_source.clone();
            move |st: &str, err: Option<String>, blocks: Option<Vec<TranscriptBlock>>| {
                let snap = {
                    let mut guard = state_arc.lock();
                    guard.state = st.to_string();
                    guard.source = source.clone();
                    guard.error = err;
                    if let Some(b) = blocks {
                        guard.blocks = b;
                    }
                    guard.clone()
                };
                on_update(snap);
            }
        };

        emit("connecting", None, Some(Vec::new()));

        let mut cfg_obj = json!({
            "model": SONIOX_MODEL,
            "audio_format": "pcm_s16le",
            "sample_rate": capture_info.sample_rate,
            "num_channels": capture_info.channels,
            "enable_language_identification": true,
            "enable_speaker_diarization": params.speaker_diarization,
            "enable_endpoint_detection": true,
            "max_endpoint_delay_ms": MAX_ENDPOINT_DELAY_MS,
            "client_reference_id": SONIOX_CLIENT_REFERENCE,
        });
        if let Some(ctx) = build_context(&params.context_text, &params.context_terms) {
            cfg_obj["context"] = ctx;
        }
        if params.translation_mode == "two_way" {
            cfg_obj["translation"] = json!({
                "type": "two_way",
                "language_a": params.language_a,
                "language_b": params.language_b,
            });
            cfg_obj["language_hints"] = json!([params.language_a, params.language_b]);
            cfg_obj["language_hints_strict"] = json!(true);
        } else {
            cfg_obj["translation"] = json!({
                "type": "one_way",
                "target_language": params.target_language,
            });
        }
        let start_msg = cfg_obj.to_string();

        let stop_slot = self.stop_flag.clone();

        tauri::async_runtime::spawn(async move {
            let mut transcript = TranscriptBuffer::default();
            let mut standby = false;
            let mut preroll: Vec<Vec<u8>> = Vec::new();
            let mut preroll_bytes = 0usize;

            'outer: while !stop.load(Ordering::Relaxed) {
                if standby {
                    // Wait for voice before opening a new billed Soniox WS connection
                    emit("standby", None, None);
                    while !stop.load(Ordering::Relaxed) {
                        match tokio::time::timeout(Duration::from_millis(250), chunk_rx.recv())
                            .await
                        {
                            Ok(Some(chunk)) => {
                                let peak = pcm_s16le_peak(&chunk);
                                preroll_bytes += chunk.len();
                                preroll.push(chunk);
                                while preroll_bytes > STANDBY_PREROLL_BYTES && preroll.len() > 1 {
                                    preroll_bytes -= preroll.remove(0).len();
                                }
                                if peak >= SILENCE_PEAK {
                                    standby = false;
                                    emit("reconnecting", None, None);
                                    break;
                                }
                            }
                            Ok(None) => break 'outer,
                            Err(_) => {}
                        }
                    }
                    if stop.load(Ordering::Relaxed) {
                        break 'outer;
                    }
                }

                // Connect WebSocket with Authorization: Bearer header
                let mut req = match SONIOX_WEBSOCKET_URL.into_client_request() {
                    Ok(r) => r,
                    Err(_) => {
                        emit(
                            "idle",
                            Some("Không kết nối được dịch vụ dịch âm thanh, vui lòng thử lại sau.".to_string()),
                            None,
                        );
                        break;
                    }
                };
                if let Ok(val) = HeaderValue::from_str(&format!("Bearer {key}")) {
                    req.headers_mut().insert("Authorization", val);
                }

                let ws_stream = match tokio_tungstenite::connect_async(req).await {
                    Ok((ws, _)) => ws,
                    Err(e) => {
                        emit(
                            "idle",
                            Some(format!("Không kết nối được Soniox WebSocket: {e}")),
                            None,
                        );
                        break;
                    }
                };

                let (mut ws_tx, mut ws_rx) = ws_stream.split();
                if ws_tx.send(Message::Text(start_msg.clone().into())).await.is_err() {
                    emit(
                        "idle",
                        Some("Không gửi được cấu hình khởi đầu tới Soniox.".to_string()),
                        None,
                    );
                    break;
                }

                emit("listening", None, None);
                // Flush preroll audio after waking from standby
                if !preroll.is_empty() {
                    for buf in preroll.drain(..) {
                        let _ = ws_tx.send(Message::Binary(buf.into())).await;
                    }
                    preroll_bytes = 0;
                }

                let mut last_sent = Instant::now();
                let mut last_voice = Instant::now();
                let mut finalize_sent = false;
                let mut tick = tokio::time::interval(Duration::from_millis(500));

                loop {
                    if stop.load(Ordering::Relaxed) {
                        // Send empty text frame for graceful finalize
                        let _ = ws_tx.send(Message::Text(String::new().into())).await;
                        let _ = ws_tx.close().await;
                        break 'outer;
                    }

                    tokio::select! {
                        maybe_chunk = chunk_rx.recv() => {
                            let Some(chunk) = maybe_chunk else { break 'outer; };
                            let peak = pcm_s16le_peak(&chunk);
                            if peak >= SILENCE_PEAK {
                                last_voice = Instant::now();
                                finalize_sent = false;
                            }
                            if ws_tx.send(Message::Binary(chunk.into())).await.is_err() {
                                break;
                            }
                            last_sent = Instant::now();
                        }
                        maybe_msg = ws_rx.next() => {
                            match maybe_msg {
                                Some(Ok(Message::Text(txt))) => {
                                    if let Ok(val) = serde_json::from_str::<Value>(&txt) {
                                        if val.get("error_code").is_some() || val.get("error_type").is_some() {
                                            let err_type = val.get("error_type").and_then(Value::as_str).unwrap_or("");
                                            let reconnectable = matches!(
                                                err_type,
                                                "max_duration_reached" | "service_unavailable" | "request_timeout" | "internal_error"
                                            );
                                            if reconnectable {
                                                transcript.non_final_tokens.clear();
                                                emit("reconnecting", None, None);
                                                tokio::time::sleep(Duration::from_millis(600)).await;
                                                break;
                                            }
                                            emit("idle", Some(describe_soniox_error(&val)), None);
                                            break 'outer;
                                        }
                                        if let Some(tokens) = val.get("tokens").and_then(Value::as_array) {
                                            transcript.ingest(tokens);
                                            emit("listening", None, Some(transcript.blocks()));
                                        }
                                        if val.get("finished").and_then(Value::as_bool).unwrap_or(false) {
                                            break 'outer;
                                        }
                                    }
                                }
                                Some(Ok(Message::Close(_))) | None => break,
                                Some(Err(_)) => break,
                                _ => {}
                            }
                        }
                        _ = tick.tick() => {
                            let silent_secs = last_voice.elapsed().as_secs_f64();
                            if silent_secs >= STANDBY_AFTER_SILENCE_SECS {
                                let _ = ws_tx.send(Message::Text(String::new().into())).await;
                                let _ = ws_tx.close().await;
                                transcript.non_final_tokens.clear();
                                standby = true;
                                break;
                            }
                            if silent_secs >= FINALIZE_AFTER_SILENCE_SECS && !finalize_sent {
                                let _ = ws_tx.send(Message::Text(r#"{"type":"finalize"}"#.into())).await;
                                finalize_sent = true;
                                last_sent = Instant::now();
                            } else if last_sent.elapsed().as_secs_f64() >= KEEPALIVE_IDLE_SECS {
                                let _ = ws_tx.send(Message::Text(r#"{"type":"keepalive"}"#.into())).await;
                                last_sent = Instant::now();
                            }
                            let _ = MAX_WAKE_BUFFER_BYTES;
                        }
                    }
                }
            }

            stop.store(true, Ordering::Relaxed);
            *stop_slot.lock() = None;
            let final_err = state_arc.lock().error.clone();
            emit("idle", final_err, None);
        });

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transcript_buffer_merges_final_and_replaces_non_final() {
        let mut buf = TranscriptBuffer::default();
        buf.ingest(&[
            json!({"text": "Hello ", "is_final": true, "language": "en", "speaker": "1"}),
            json!({"text": "world", "is_final": false, "language": "en", "speaker": "1"}),
        ]);
        let b1 = buf.blocks();
        assert_eq!(b1.len(), 1);
        assert_eq!(b1[0].text, "Hello world");
        assert!(!b1[0].is_final);

        buf.ingest(&[
            json!({"text": "there", "is_final": true, "language": "en", "speaker": "1"}),
            json!({"text": "Xin chào", "is_final": true, "language": "vi", "translation_status": "translation", "speaker": "1"}),
        ]);
        let b2 = buf.blocks();
        assert_eq!(b2.len(), 2);
        assert_eq!(b2[0].text, "Hello there");
        assert!(b2[0].is_final);
        assert_eq!(b2[1].kind, "translation");
        assert_eq!(b2[1].text, "Xin chào");
    }

    #[test]
    fn context_parses_terms_and_translation_pairs() {
        let ctx = build_context("RPG game", "Gojo => Gojo, Hollow Purple → Tử Thức, Mana").unwrap();
        assert_eq!(ctx["text"], "RPG game");
        assert_eq!(ctx["translation_terms"].as_array().unwrap().len(), 2);
        assert_eq!(ctx["terms"].as_array().unwrap().len(), 3);
    }
}
