//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

use crate::api::wasm32::http::fetch_api;

/// A `SupportedFormat` struct.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct SupportedFormat {
    pub format: String,
    pub width: u32,
    pub height: u32,
    #[serde(default)]
    pub fps: Vec<u32>,
}

/// A `CameraDevice` struct.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct CameraDevice {
    pub path: String,
    pub index: i32,
    pub name: String,
    #[serde(default)]
    pub supported_formats: Vec<SupportedFormat>,
}

/// A `CameraDevicesResponse` struct.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct CameraDevicesResponse {
    pub devices: Vec<CameraDevice>,
    pub current_device: String,
    pub current_index: u32,
    pub current_width: u32,
    pub current_height: u32,
    pub current_framerate: u32,
    pub current_auto_exposure: bool,
    pub current_exposure_time: u32,
    pub current_rgb_red: u16,
    pub current_rgb_green: u16,
    pub current_rgb_blue: u16,
    pub current_gamma: u32,
    #[serde(default = "default_gain")]
    pub current_gain: u32,
    #[serde(default = "default_exposure_min")]
    pub exposure_time_min: u32,
    #[serde(default = "default_exposure_max")]
    pub exposure_time_max: u32,
    #[serde(default)]
    pub current_stereo_enabled: bool,
    #[serde(default = "default_stereo_alpha")]
    pub current_stereo_blend_alpha: f32,
    #[serde(default)]
    pub current_stereo_offset: f32,
    #[serde(default)]
    pub current_stereo_offset_y: f32,
}

/// Default stereo alpha.
fn default_stereo_alpha() -> f32 {
    0.5
}

/// Default exposure min.
fn default_exposure_min() -> u32 {
    1
}
/// Default exposure max.
fn default_exposure_max() -> u32 {
    300_000
}

/// Default gain.
fn default_gain() -> u32 {
    0
}

/// GET /api/v1/camera/devices — list V4L2 devices + current webcam-server config
pub async fn get_camera_devices() -> Result<CameraDevicesResponse, String> {
    fetch_api::<CameraDevicesResponse>("/api/v1/camera/devices", "GET", None).await
}

/// POST /api/v1/camera/config — push partial config to the webcam server
pub async fn update_camera_config(
    camera_index: Option<u32>,
    width: Option<u32>,
    height: Option<u32>,
    framerate: Option<u32>,
    auto_exposure: Option<bool>,
    exposure_time: Option<u32>,
    rgb_red: Option<u16>,
    rgb_green: Option<u16>,
    rgb_blue: Option<u16>,
    gamma: Option<u32>,
    gain: Option<u32>,
) -> Result<(), String> {
    let mut patch = serde_json::Map::new();
    if let Some(v) = camera_index {
        patch.insert("camera_index".to_string(), serde_json::json!(v));
    }
    if let Some(v) = width {
        patch.insert("width".to_string(), serde_json::json!(v));
    }
    if let Some(v) = height {
        patch.insert("height".to_string(), serde_json::json!(v));
    }
    if let Some(v) = framerate {
        patch.insert("framerate".to_string(), serde_json::json!(v));
    }
    if let Some(v) = auto_exposure {
        patch.insert("auto_exposure".to_string(), serde_json::json!(v));
    }
    if let Some(v) = exposure_time {
        patch.insert("exposure_time".to_string(), serde_json::json!(v));
    }
    if let Some(v) = rgb_red {
        patch.insert("rgb_red".to_string(), serde_json::json!(v));
    }
    if let Some(v) = rgb_green {
        patch.insert("rgb_green".to_string(), serde_json::json!(v));
    }
    if let Some(v) = rgb_blue {
        patch.insert("rgb_blue".to_string(), serde_json::json!(v));
    }
    if let Some(v) = gamma {
        patch.insert("gamma".to_string(), serde_json::json!(v));
    }
    if let Some(v) = gain {
        patch.insert("gain".to_string(), serde_json::json!(v));
    }
    let body = serde_json::Value::Object(patch).to_string();
    fetch_api::<serde_json::Value>("/api/v1/camera/config", "POST", Some(&body))
        .await
        .map(|_| ())
}

/// POST /api/v1/camera/config — push only the stereo combine settings.
/// Applied immediately by the inference-service (no camera restart).
pub async fn update_stereo_config(
    enabled: Option<bool>,
    blend_alpha: Option<f32>,
    offset: Option<f32>,
    offset_y: Option<f32>,
) -> Result<(), String> {
    let mut patch = serde_json::Map::new();
    if let Some(v) = enabled {
        patch.insert("stereo_enabled".to_string(), serde_json::json!(v));
    }
    if let Some(v) = blend_alpha {
        patch.insert("stereo_blend_alpha".to_string(), serde_json::json!(v));
    }
    if let Some(v) = offset {
        patch.insert("stereo_offset".to_string(), serde_json::json!(v));
    }
    if let Some(v) = offset_y {
        patch.insert("stereo_offset_y".to_string(), serde_json::json!(v));
    }
    let body = serde_json::Value::Object(patch).to_string();
    fetch_api::<serde_json::Value>("/api/v1/camera/config", "POST", Some(&body))
        .await
        .map(|_| ())
}
