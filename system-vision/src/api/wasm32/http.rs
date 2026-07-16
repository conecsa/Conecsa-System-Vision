//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

/// Low-level HTTP transport helpers used by all wasm32 services.
use prost::Message;
use serde::Deserialize;
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;
use web_sys::{Request, RequestInit, RequestMode, Response};

use crate::app::get_api_base_url;

/// Set headers.
fn set_headers(request: &Request, headers: &[(&str, &str)]) -> Result<(), String> {
    for (name, value) in headers {
        request
            .headers()
            .set(name, value)
            .map_err(|e| format!("Failed to set {} header: {:?}", name, e))?;
    }
    Ok(())
}

/// Generic JSON fetch – used by services that communicate via REST/JSON.
pub async fn fetch_api<T: for<'de> Deserialize<'de>>(
    endpoint: &str,
    method: &str,
    body: Option<&str>,
) -> Result<T, String> {
    let window = web_sys::window().ok_or("No window object")?;
    let base_url = get_api_base_url();
    let url = format!("{}{}", base_url, endpoint);

    web_sys::console::log_1(&format!("Fetching: {} {}", method, url).into());

    let opts = RequestInit::new();
    opts.set_method(method);
    opts.set_mode(RequestMode::Cors);

    if let Some(body_str) = body {
        web_sys::console::log_1(&format!("Request body: {}", body_str).into());
        opts.set_body(&JsValue::from_str(body_str));
    }

    let request = Request::new_with_str_and_init(&url, &opts)
        .map_err(|e| format!("Failed to create request: {:?}", e))?;

    request
        .headers()
        .set("Content-Type", "application/json")
        .map_err(|e| format!("Failed to set Content-Type: {:?}", e))?;
    request
        .headers()
        .set("Accept", "application/json")
        .map_err(|e| format!("Failed to set Accept: {:?}", e))?;
    request
        .headers()
        .set("X-Conecsa-Source", "frontend")
        .map_err(|e| format!("Failed to set X-Conecsa-Source: {:?}", e))?;

    let resp_value = JsFuture::from(window.fetch_with_request(&request))
        .await
        .map_err(|e| {
            web_sys::console::error_1(&format!("Fetch error: {:?}", e).into());
            format!("Fetch failed: {:?}", e)
        })?;

    let resp: Response = resp_value
        .dyn_into()
        .map_err(|_| "Response is not a Response object")?;

    web_sys::console::log_1(&format!("Response status: {}", resp.status()).into());

    if !resp.ok() {
        // Surface the backend's error body ({"error": ...} / {"message": ...})
        // instead of a bare status code — these strings land in user-facing
        // toasts and are often the only diagnostic (e.g. SAM load failures).
        let status = resp.status();
        let mut detail = String::new();
        if let Ok(text_promise) = resp.text() {
            if let Ok(text_value) = JsFuture::from(text_promise).await {
                if let Some(text) = text_value.as_string() {
                    detail = serde_json::from_str::<serde_json::Value>(&text)
                        .ok()
                        .and_then(|v| {
                            ["error", "message"]
                                .iter()
                                .find_map(|k| v.get(k)?.as_str().map(String::from))
                        })
                        .unwrap_or(text);
                    if detail.len() > 300 {
                        detail = detail.chars().take(300).collect();
                    }
                }
            }
        }
        return Err(if detail.trim().is_empty() {
            format!("HTTP error: {}", status)
        } else {
            format!("HTTP {}: {}", status, detail.trim())
        });
    }

    let json = JsFuture::from(
        resp.json()
            .map_err(|e| format!("Failed to parse JSON: {:?}", e))?,
    )
    .await
    .map_err(|e| format!("JSON parse failed: {:?}", e))?;

    web_sys::console::log_1(&format!("Response JSON: {:?}", json).into());

    serde_wasm_bindgen::from_value(json).map_err(|e| {
        web_sys::console::error_1(&format!("Deserialization error: {:?}", e).into());
        format!("Deserialization failed: {:?}", e)
    })
}

/// Generic Protobuf fetch – used by services that communicate via protobuf.
pub async fn fetch_protobuf<T: Message + Default>(
    endpoint: &str,
    method: &str,
    body: Option<&[u8]>,
) -> Result<T, String> {
    let window = web_sys::window().ok_or("No window object")?;
    let base_url = get_api_base_url();
    let url = format!("{}{}", base_url, endpoint);

    let opts = RequestInit::new();
    opts.set_method(method);
    opts.set_mode(RequestMode::Cors);

    if let Some(body_bytes) = body {
        use js_sys::Uint8Array;
        let array = Uint8Array::new_with_length(body_bytes.len() as u32);
        array.copy_from(body_bytes);
        opts.set_body(&array);
    }

    let request = Request::new_with_str_and_init(&url, &opts)
        .map_err(|e| format!("Failed to create request: {:?}", e))?;

    set_headers(
        &request,
        &[
            ("Content-Type", "application/x-protobuf"),
            ("Accept", "application/x-protobuf"),
            ("X-Conecsa-Source", "frontend"),
        ],
    )?;

    let resp_value = JsFuture::from(window.fetch_with_request(&request))
        .await
        .map_err(|e| format!("Fetch failed: {:?}", e))?;

    let resp: Response = resp_value
        .dyn_into()
        .map_err(|_| "Response is not a Response object")?;

    let array_buffer = JsFuture::from(
        resp.array_buffer()
            .map_err(|e| format!("Failed to get array buffer: {:?}", e))?,
    )
    .await
    .map_err(|e| format!("Failed to read array buffer: {:?}", e))?;

    use js_sys::Uint8Array;
    let uint8_array = Uint8Array::new(&array_buffer);
    let mut bytes = vec![0u8; uint8_array.length() as usize];
    uint8_array.copy_to(&mut bytes);

    T::decode(&bytes[..]).map_err(|e| format!("Failed to decode protobuf: {}", e))
}
