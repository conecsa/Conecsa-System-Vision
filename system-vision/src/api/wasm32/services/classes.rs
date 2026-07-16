//! Object-class management (HTTP/JSON).

use serde::Deserialize;
use wasm_bindgen_futures::JsFuture;

use crate::api::wasm32::http::fetch_api;

/// Get classes.
pub async fn get_classes() -> Result<Vec<String>, String> {
    /// A `ClassesResponse` struct.
    #[derive(Deserialize)]
    struct ClassesResponse {
        classes: Vec<String>,
    }

    let response = fetch_api::<ClassesResponse>("/api/v1/classes", "GET", None).await?;
    Ok(response.classes)
}

/// Upload classes.
pub async fn upload_classes(classes: Vec<String>) -> Result<(), String> {
    let body = serde_json::json!({ "classes": classes }).to_string();
    fetch_api::<serde_json::Value>("/api/v1/classes", "POST", Some(&body))
        .await
        .map(|_| ())
}

/// Clear classes.
pub async fn clear_classes() -> Result<(), String> {
    fetch_api::<serde_json::Value>("/api/v1/classes", "DELETE", None)
        .await
        .map(|_| ())
}

/// Upload classes directly from a browser `File` object (web only)
pub async fn upload_classes_file(file: web_sys::File) -> Result<(), String> {
    use js_sys::Uint8Array;

    let array_buffer = JsFuture::from(file.array_buffer())
        .await
        .map_err(|e| format!("Failed to read file: {:?}", e))?;

    let uint8_array = Uint8Array::new(&array_buffer);
    let mut bytes = vec![0; uint8_array.length() as usize];
    uint8_array.copy_to(&mut bytes);

    let content = String::from_utf8(bytes).map_err(|e| format!("Invalid UTF-8: {}", e))?;

    let classes = crate::api::parse_classes_text(&content);

    if classes.is_empty() {
        return Err("No valid classes found in file".to_string());
    }

    upload_classes(classes).await
}

/// Upload classes via native file dialog — unsupported in the web build.
pub async fn upload_classes_dialog() -> Result<(), String> {
    Err("Classes upload via file dialog is only available in the desktop app".to_string())
}
