//! Model management (HTTP/JSON + multipart upload).

use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;
use web_sys::{Request, RequestInit, RequestMode, Response};

use crate::api::wasm32::http::fetch_api;
use crate::app::get_api_base_url;

/// Response returned by POST /api/v1/model
#[derive(Debug, Clone, serde::Deserialize)]
pub struct UploadModelResponse {
    pub status: String, // "success" | "converting"
    pub message: String,
    pub job_id: Option<String>, // present only when status == "converting"
    pub filename: Option<String>,
    pub model: Option<String>,
}

/// Conversion status returned by GET /api/v1/model/conversion/<job_id>
#[derive(Debug, Clone, serde::Deserialize)]
pub struct ConversionStatusResponse {
    pub job_id: String,
    pub original_filename: String,
    pub status: String, // "pending" | "converting_to_onnx" | "converting_to_engine" | "done" | "failed"
    pub progress: u8,
    pub message: String,
    pub error: Option<String>,
    pub engine_filename: Option<String>,
    pub auto_select_hint: Option<String>,
    pub started_at: Option<f64>, // UNIX timestamp in seconds
}

/// Response from GET /api/v1/model/conversion (list active jobs)
#[derive(Debug, Clone, serde::Deserialize)]
pub struct ActiveConversionsResponse {
    pub jobs: Vec<ConversionStatusResponse>,
}

/// List all active (non-terminal) conversion jobs
pub async fn list_active_conversions() -> Result<ActiveConversionsResponse, String> {
    fetch_api::<ActiveConversionsResponse>("/api/v1/model/conversion", "GET", None).await
}

/// Query the status of an async conversion job
pub async fn get_conversion_status(job_id: &str) -> Result<ConversionStatusResponse, String> {
    let url = format!("/api/v1/model/conversion/{}", job_id);
    fetch_api::<ConversionStatusResponse>(&url, "GET", None).await
}

/// Upload model file from browser – returns rich response (job_id when .pt)
pub async fn upload_model_file(file: web_sys::File) -> Result<UploadModelResponse, String> {
    use web_sys::FormData;

    let window = web_sys::window().ok_or("No window object")?;
    let base_url = get_api_base_url();
    let url = format!("{}/api/v1/model", base_url);

    let form_data = FormData::new().map_err(|e| format!("Failed to create FormData: {:?}", e))?;
    form_data
        .append_with_blob("file", &file)
        .map_err(|e| format!("Failed to append file to FormData: {:?}", e))?;

    let opts = RequestInit::new();
    opts.set_method("POST");
    opts.set_mode(RequestMode::Cors);
    opts.set_body(&form_data);

    let request = Request::new_with_str_and_init(&url, &opts)
        .map_err(|e| format!("Failed to create request: {:?}", e))?;
    request
        .headers()
        .set("X-Conecsa-Source", "frontend")
        .map_err(|e| format!("Failed to set X-Conecsa-Source: {:?}", e))?;

    let resp_value = JsFuture::from(window.fetch_with_request(&request))
        .await
        .map_err(|e| format!("Upload failed: {:?}", e))?;

    let resp: Response = resp_value
        .dyn_into()
        .map_err(|_| "Response is not a Response object")?;

    if !resp.ok() {
        let status = resp.status();
        let text = JsFuture::from(
            resp.text()
                .map_err(|e| format!("Failed to read error response: {:?}", e))?,
        )
        .await
        .map_err(|e| format!("Failed to parse error text: {:?}", e))?;
        let error_text = text
            .as_string()
            .unwrap_or_else(|| "Unknown error".to_string());
        return Err(format!(
            "Upload failed with status {}: {}",
            status, error_text
        ));
    }

    let text_js = JsFuture::from(
        resp.text()
            .map_err(|e| format!("Failed to read response: {:?}", e))?,
    )
    .await
    .map_err(|e| format!("Failed to parse response text: {:?}", e))?;

    let text = text_js.as_string().unwrap_or_else(|| "{}".to_string());
    serde_json::from_str::<UploadModelResponse>(&text)
        .map_err(|e| format!("Failed to parse upload response: {} — body: {}", e, text))
}

/// Upload model via native file dialog — unsupported in the web build.
pub async fn upload_model_dialog() -> Result<(), String> {
    Err(
        "Model upload via file dialog is only available in the desktop app. \
         Please upload directly via the Python API endpoint: POST /api/v1/model"
            .to_string(),
    )
}

/// Select a model by name
pub async fn select_model(model_name: &str) -> Result<(), String> {
    let body = serde_json::json!({ "model_name": model_name }).to_string();
    fetch_api::<serde_json::Value>("/api/v1/model/select", "POST", Some(&body))
        .await
        .map(|_| ())
}

/// URL that downloads a model file (gateway sets the Content-Disposition filename).
pub fn model_download_url(model_name: &str) -> String {
    // Percent-encode: model names are upload filenames and may contain spaces.
    let encoded = String::from(js_sys::encode_uri_component(model_name));
    format!("{}/api/v1/model/{}/download", get_api_base_url(), encoded)
}

/// Delete a model by name
pub async fn delete_model(model_name: &str) -> Result<(), String> {
    let url = format!("/api/v1/model/{}", model_name);
    fetch_api::<serde_json::Value>(&url, "DELETE", None)
        .await
        .map(|_| ())
}
