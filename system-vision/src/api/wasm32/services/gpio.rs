//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

use crate::api::wasm32::http::fetch_api;

/// Resposta do endpoint GET /api/v1/gpio/status
#[derive(Debug, Clone, serde::Deserialize)]
pub struct GpioStatus {
    pub gpio_available: bool,
    pub gpio_enabled: bool,
    pub trigger_pin: u8,
    pub output_pins: Vec<u8>,
    pub trigger_state: Option<bool>,
}

/// Resposta do endpoint POST /api/v1/gpio/trigger
#[derive(Debug, Clone, serde::Deserialize)]
pub struct GpioTriggerResponse {
    pub success: bool,
    pub gpio_enabled: bool,
    pub message: String,
}

/// GET /api/v1/gpio/status
pub async fn get_gpio_status() -> Result<GpioStatus, String> {
    fetch_api::<GpioStatus>("/api/v1/gpio/status", "GET", None).await
}

/// POST /api/v1/gpio/trigger — habilita ou desabilita trigger via GPIO
pub async fn set_gpio_trigger(enabled: bool) -> Result<GpioTriggerResponse, String> {
    let body = serde_json::json!({ "enabled": enabled }).to_string();
    fetch_api::<GpioTriggerResponse>("/api/v1/gpio/trigger", "POST", Some(&body)).await
}
