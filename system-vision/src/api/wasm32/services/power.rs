//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

use crate::api::wasm32::http::fetch_api;

/// Response from POST /api/v1/system/power
#[derive(Debug, Clone, serde::Deserialize)]
pub struct SystemPowerResponse {
    pub success: bool,
    pub message: String,
}

/// POST /api/v1/system/power — shuts down or restarts the controller host.
///
/// `action` must be `"shutdown"` or `"restart"`.
pub async fn system_power(action: &str) -> Result<SystemPowerResponse, String> {
    let body = serde_json::json!({ "action": action }).to_string();
    fetch_api::<SystemPowerResponse>("/api/v1/system/power", "POST", Some(&body)).await
}
