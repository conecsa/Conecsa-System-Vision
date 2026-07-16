//! The root Leptos `App` component and shared frontend helpers
//! (API base-URL resolution, fetch wrapper, formatting).

use leptos::prelude::*;
use serde::{Deserialize, Serialize};
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;
use web_sys::{Request, RequestInit, RequestMode, Response};

use crate::components::MainView;
use crate::i18n::*;
pub use crate::models::{ModelInfo, PerformanceStats, ProtocolInfo, SystemStatus};

/// A `ModelsResponse` struct.
#[derive(Clone, Debug, Serialize, Deserialize)]
struct ModelsResponse {
    models: Vec<ModelInfo>,
}

/// The `App` view component.
#[component]
pub fn App() -> impl IntoView {
    crate::components::locale::init_locale();
    crate::components::access::init_access();
    view! {
        <MainView />
    }
}

// Helper functions
/// Refresh status.
pub async fn refresh_status(
    set_status: WriteSignal<Option<SystemStatus>>,
    set_error_msg: WriteSignal<String>,
) {
    let result = fetch_api::<SystemStatus>("/api/v1/status", "GET", None).await;

    match result {
        Ok(status) => {
            set_status.set(Some(status));
            set_error_msg.set(String::new());
        }
        Err(e) => {
            set_error_msg.set(e);
        }
    }
}

/// Check api health.
pub async fn check_api_health(set_api_health: WriteSignal<bool>) {
    match fetch_api::<serde_json::Value>("/api/v1/health", "GET", None).await {
        Ok(_) => set_api_health.set(true),
        Err(_) => set_api_health.set(false),
    }
}

/// Load models. Takes the locale captured by the caller so the error message
/// is localized (this helper runs outside any reactive context).
pub async fn load_models(
    set_models: WriteSignal<Vec<ModelInfo>>,
    set_error_msg: WriteSignal<String>,
    locale: Locale,
) {
    match fetch_api::<ModelsResponse>("/api/v1/models", "GET", None).await {
        Ok(response) => set_models.set(response.models),
        Err(e) => set_error_msg.set(td_string!(locale, common::failed_to_load_models, err = e)),
    }
}

// Generic HTTP fetch function for web mode
/// Fetch api.
async fn fetch_api<T: for<'de> Deserialize<'de>>(
    endpoint: &str,
    method: &str,
    body: Option<&str>,
) -> Result<T, String> {
    let window = web_sys::window().ok_or("No window object")?;

    // Use dynamic base URL that supports WSL and multiple environments
    let base_url = get_api_base_url();
    let url = format!("{}{}", base_url, endpoint);

    let opts = RequestInit::new();
    opts.set_method(method);
    opts.set_mode(RequestMode::Cors);

    if let Some(body_str) = body {
        opts.set_body(&JsValue::from_str(body_str));
    }

    let request = Request::new_with_str_and_init(&url, &opts)
        .map_err(|e| format!("Failed to create request: {:?}", e))?;

    request
        .headers()
        .set("Content-Type", "application/json")
        .map_err(|e| format!("Failed to set header: {:?}", e))?;
    request
        .headers()
        .set("X-Conecsa-Source", "frontend")
        .map_err(|e| format!("Failed to set header: {:?}", e))?;

    let resp_value = JsFuture::from(window.fetch_with_request(&request))
        .await
        .map_err(|e| format!("Fetch failed: {:?}", e))?;

    let resp: Response = resp_value
        .dyn_into()
        .map_err(|_| "Response is not a Response object")?;

    if !resp.ok() {
        return Err(format!("HTTP error: {}", resp.status()));
    }

    let json = JsFuture::from(
        resp.json()
            .map_err(|e| format!("Failed to parse JSON: {:?}", e))?,
    )
    .await
    .map_err(|e| format!("JSON parse failed: {:?}", e))?;

    serde_wasm_bindgen::from_value(json).map_err(|e| format!("Deserialization failed: {:?}", e))
}

/// API base URL — same origin. The app is served by the device's nginx (directly
/// or through the hub's local mTLS reverse proxy), which routes `/api` to the
/// api-gateway. Using a relative base means requests inherit the serving origin,
/// so the UI works at `:80`, behind `:443` mTLS, and through `127.0.0.1:<proxy>`.
pub fn get_api_base_url() -> String {
    String::new()
}

/// Node-RED editor URL — proxied under `/flow` on the same origin (Node-RED is
/// configured with `httpAdminRoot=/flow`).
pub fn get_node_red_url() -> String {
    "/flow/".to_string()
}

/// Format size.
pub fn format_size(size: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = KB * 1024;
    const GB: u64 = MB * 1024;

    if size >= GB {
        format!("{:.2} GB", size as f64 / GB as f64)
    } else if size >= MB {
        format!("{:.2} MB", size as f64 / MB as f64)
    } else if size >= KB {
        format!("{:.2} KB", size as f64 / KB as f64)
    } else {
        format!("{} B", size)
    }
}

#[cfg(test)]
mod tests;
