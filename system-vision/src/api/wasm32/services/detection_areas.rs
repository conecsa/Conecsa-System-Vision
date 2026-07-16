//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

/// Detection-area HTTP client. Mirrors `/api/v1/detection-areas/*` endpoints.
use serde::Deserialize;

use crate::api::wasm32::http::fetch_api;

/// A `DetectionArea` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct DetectionArea {
    pub id: String,
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
    pub is_editing: bool,
    #[serde(default = "default_shape")]
    pub shape: String,
}

/// Default shape.
fn default_shape() -> String {
    "rectangle".to_string()
}

/// A `DetectionAreasResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct DetectionAreasResponse {
    pub areas: Vec<DetectionArea>,
}

/// List detection areas.
pub async fn list_detection_areas() -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>("/api/v1/detection-areas", "GET", None).await
}

/// Create detection area.
pub async fn create_detection_area() -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>("/api/v1/detection-areas", "POST", Some("{}")).await
}

/// Delete detection area.
pub async fn delete_detection_area(id: &str) -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>(&format!("/api/v1/detection-areas/{}", id), "DELETE", None)
        .await
}

/// Save detection area.
pub async fn save_detection_area(id: &str) -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>(
        &format!("/api/v1/detection-areas/{}/save", id),
        "POST",
        Some("{}"),
    )
    .await
}

/// Send area command.
pub async fn send_area_command(id: &str, action: &str) -> Result<DetectionAreasResponse, String> {
    let body = serde_json::json!({ "action": action }).to_string();
    fetch_api::<DetectionAreasResponse>(
        &format!("/api/v1/detection-areas/{}/command", id),
        "POST",
        Some(&body),
    )
    .await
}

/// Edit detection area.
pub async fn edit_detection_area(id: &str) -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>(
        &format!("/api/v1/detection-areas/{}/edit", id),
        "POST",
        Some("{}"),
    )
    .await
}

/// Discard detection area.
pub async fn discard_detection_area(id: &str) -> Result<DetectionAreasResponse, String> {
    fetch_api::<DetectionAreasResponse>(
        &format!("/api/v1/detection-areas/{}/discard", id),
        "POST",
        Some("{}"),
    )
    .await
}

/// Set area shape.
pub async fn set_area_shape(id: &str, shape: &str) -> Result<DetectionAreasResponse, String> {
    let body = serde_json::json!({ "shape": shape }).to_string();
    fetch_api::<DetectionAreasResponse>(
        &format!("/api/v1/detection-areas/{}/shape", id),
        "POST",
        Some(&body),
    )
    .await
}
