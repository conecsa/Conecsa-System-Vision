//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

/// Training-service HTTP client. Mirrors `/api/v1/training/*` (api-gateway).
/// Every dataset-scoped call carries the dataset_id (stateless backend).
use serde::{Deserialize, Serialize};
use wasm_bindgen::prelude::*;
use wasm_bindgen_futures::JsFuture;
use web_sys::{Request, RequestInit, RequestMode, Response};

use crate::api::wasm32::http::fetch_api;
use crate::app::get_api_base_url;

/// A `DatasetSummary` struct.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct DatasetSummary {
    pub dataset_id: String,
    pub name: String,
    #[serde(default)]
    pub created_at: f64,
    #[serde(default)]
    pub cover_image_id: String,
    #[serde(default)]
    pub image_count: u32,
    #[serde(default)]
    pub labeled_count: u32,
    #[serde(default)]
    pub class_count: u32,
}

/// A `DatasetsResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct DatasetsResponse {
    pub datasets: Vec<DatasetSummary>,
}

/// A `DatasetUploadResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct DatasetUploadResponse {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    pub dataset: Option<DatasetSummary>,
}

/// A `TrainingDatasetInfo` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct TrainingDatasetInfo {
    pub image_count: u32,
    pub labeled_count: u32,
    pub classes: Vec<String>,
    pub min_images: u32,
    #[serde(default)]
    pub dataset_id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub cover_image_id: String,
}

/// A `TrainingImageInfo` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct TrainingImageInfo {
    pub image_id: String,
    pub created_at: f64,
    pub labeled: bool,
    pub box_count: u32,
    #[serde(default)]
    pub replica: bool,
}

/// A `TrainingImagesResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct TrainingImagesResponse {
    pub images: Vec<TrainingImageInfo>,
}

/// A `LabelBox` struct.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LabelBox {
    #[serde(default)]
    pub class_id: u32,
    pub cx: f32,
    pub cy: f32,
    pub w: f32,
    pub h: f32,
}

/// A `LabelsResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct LabelsResponse {
    pub image_id: String,
    pub boxes: Vec<LabelBox>,
}

/// A `ClassesResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct ClassesResponse {
    pub classes: Vec<String>,
}

/// A `SamStatusResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct SamStatusResponse {
    pub available: bool,
    pub loaded: bool,
    #[serde(default)]
    pub message: String,
}

/// A `SamSegmentResponse` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct SamSegmentResponse {
    pub boxes: Vec<LabelBox>,
    #[serde(default)]
    pub scores: Vec<f32>,
}

/// A `TrainingJobStatus` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct TrainingJobStatus {
    #[serde(default)]
    pub job_id: String,
    pub status: String,
    #[serde(default)]
    pub progress: u8,
    #[serde(default)]
    pub epoch: u32,
    #[serde(default)]
    pub total_epochs: u32,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub model_name: String,
    #[serde(default)]
    pub conversion_job_id: String,
    #[serde(default)]
    pub started_at: f64,
    #[serde(default)]
    pub dataset_id: String,
}

/// A `SimpleResult` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct SimpleResult {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
}

/// URL for an `<img>` tag showing one dataset image.
pub fn training_image_url(dataset_id: &str, image_id: &str) -> String {
    format!(
        "{}/api/v1/training/datasets/{}/images/{}",
        get_api_base_url(),
        dataset_id,
        image_id
    )
}

/// URL that downloads a dataset as a YOLO-format ZIP (gateway sets the
/// Content-Disposition filename).
pub fn training_dataset_export_url(dataset_id: &str) -> String {
    format!(
        "{}/api/v1/training/datasets/{}/export",
        get_api_base_url(),
        dataset_id
    )
}

/// URL for the live combined-camera MJPEG preview on the training page.
pub fn training_preview_url() -> String {
    format!("{}/api/v1/training/preview", get_api_base_url())
}

/// Training enter.
pub async fn training_enter() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/enter", "POST", Some("{}")).await
}

/// Leave training mode. `resume_detection` = false when training just finished
/// (the model is being converted/optimized) so inference detection is NOT
/// restarted; true for a plain manual exit.
pub async fn training_exit(resume_detection: bool) -> Result<SimpleResult, String> {
    let body = serde_json::json!({ "resume_detection": resume_detection }).to_string();
    fetch_api("/api/v1/training/exit", "POST", Some(&body)).await
}

/// Keep the gateway's orphan-training watchdog fed while the training page
/// is mounted (fire-and-forget; callers ignore the result).
pub async fn training_heartbeat() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/heartbeat", "POST", Some("{}")).await
}

// ── dataset registry ─────────────────────────────────────────────────────────

/// List datasets.
pub async fn list_datasets() -> Result<DatasetsResponse, String> {
    fetch_api("/api/v1/training/datasets", "GET", None).await
}

/// Create dataset.
pub async fn create_dataset(name: &str) -> Result<DatasetSummary, String> {
    let body = serde_json::json!({ "name": name }).to_string();
    fetch_api("/api/v1/training/datasets", "POST", Some(&body)).await
}

/// Rename dataset.
pub async fn rename_dataset(dataset_id: &str, name: &str) -> Result<DatasetSummary, String> {
    let body = serde_json::json!({ "name": name }).to_string();
    fetch_api(
        &format!("/api/v1/training/datasets/{}", dataset_id),
        "PUT",
        Some(&body),
    )
    .await
}

/// Delete dataset.
pub async fn delete_dataset(dataset_id: &str) -> Result<SimpleResult, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}", dataset_id),
        "DELETE",
        None,
    )
    .await
}

/// Set dataset cover.
pub async fn set_dataset_cover(dataset_id: &str, image_id: &str) -> Result<SimpleResult, String> {
    let body = serde_json::json!({ "image_id": image_id }).to_string();
    fetch_api(
        &format!("/api/v1/training/datasets/{}/cover", dataset_id),
        "PUT",
        Some(&body),
    )
    .await
}

/// Upload a YOLO-formatted dataset ZIP as a new dataset named `name`.
/// Multipart POST; the gateway streams the file to the training-service,
/// which validates the structure and rejects incompatible archives.
pub async fn upload_dataset_zip(
    file: web_sys::File,
    name: &str,
) -> Result<DatasetUploadResponse, String> {
    use web_sys::FormData;

    let window = web_sys::window().ok_or("No window object")?;
    let url = format!("{}/api/v1/training/datasets/upload", get_api_base_url());

    let form_data = FormData::new().map_err(|e| format!("Failed to create FormData: {:?}", e))?;
    form_data
        .append_with_blob("file", &file)
        .map_err(|e| format!("Failed to append file to FormData: {:?}", e))?;
    form_data
        .append_with_str("name", name)
        .map_err(|e| format!("Failed to append name to FormData: {:?}", e))?;

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

    let text_js = JsFuture::from(
        resp.text()
            .map_err(|e| format!("Failed to read response: {:?}", e))?,
    )
    .await
    .map_err(|e| format!("Failed to parse response text: {:?}", e))?;
    let text = text_js.as_string().unwrap_or_else(|| "{}".to_string());

    if !resp.ok() {
        // The gateway returns {"error": "..."} with the validation detail.
        let detail = serde_json::from_str::<serde_json::Value>(&text)
            .ok()
            .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(String::from))
            .unwrap_or(text);
        return Err(detail);
    }
    serde_json::from_str::<DatasetUploadResponse>(&text)
        .map_err(|e| format!("Failed to parse upload response: {} — body: {}", e, text))
}

// ── dataset-scoped operations ────────────────────────────────────────────────

/// Get training dataset.
pub async fn get_training_dataset(dataset_id: &str) -> Result<TrainingDatasetInfo, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}", dataset_id),
        "GET",
        None,
    )
    .await
}

/// Capture training image.
pub async fn capture_training_image(dataset_id: &str) -> Result<TrainingImageInfo, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}/capture", dataset_id),
        "POST",
        Some("{}"),
    )
    .await
}

/// List training images.
pub async fn list_training_images(dataset_id: &str) -> Result<TrainingImagesResponse, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}/images", dataset_id),
        "GET",
        None,
    )
    .await
}

/// Delete training image.
pub async fn delete_training_image(
    dataset_id: &str,
    image_id: &str,
) -> Result<SimpleResult, String> {
    fetch_api(
        &format!(
            "/api/v1/training/datasets/{}/images/{}",
            dataset_id, image_id
        ),
        "DELETE",
        None,
    )
    .await
}

/// Replicate a labeled image (image + its labels) `count` times to grow the
/// dataset. Backend rejects unlabeled or already-replicated sources.
pub async fn replicate_training_image(
    dataset_id: &str,
    image_id: &str,
    count: u32,
) -> Result<SimpleResult, String> {
    let body = serde_json::json!({ "count": count }).to_string();
    fetch_api(
        &format!(
            "/api/v1/training/datasets/{}/images/{}/replicate",
            dataset_id, image_id
        ),
        "POST",
        Some(&body),
    )
    .await
}

/// Get training labels.
pub async fn get_training_labels(
    dataset_id: &str,
    image_id: &str,
) -> Result<LabelsResponse, String> {
    fetch_api(
        &format!(
            "/api/v1/training/datasets/{}/images/{}/labels",
            dataset_id, image_id
        ),
        "GET",
        None,
    )
    .await
}

/// Set training labels.
pub async fn set_training_labels(
    dataset_id: &str,
    image_id: &str,
    boxes: &[LabelBox],
) -> Result<SimpleResult, String> {
    let body = serde_json::json!({ "boxes": boxes }).to_string();
    fetch_api(
        &format!(
            "/api/v1/training/datasets/{}/images/{}/labels",
            dataset_id, image_id
        ),
        "PUT",
        Some(&body),
    )
    .await
}

/// Get training classes.
pub async fn get_training_classes(dataset_id: &str) -> Result<ClassesResponse, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}/classes", dataset_id),
        "GET",
        None,
    )
    .await
}

/// Add training class.
pub async fn add_training_class(dataset_id: &str, name: &str) -> Result<ClassesResponse, String> {
    let body = serde_json::json!({ "name": name }).to_string();
    fetch_api(
        &format!("/api/v1/training/datasets/{}/classes", dataset_id),
        "POST",
        Some(&body),
    )
    .await
}

/// Rename training class.
pub async fn rename_training_class(
    dataset_id: &str,
    index: usize,
    name: &str,
) -> Result<ClassesResponse, String> {
    let body = serde_json::json!({ "name": name }).to_string();
    fetch_api(
        &format!("/api/v1/training/datasets/{}/classes/{}", dataset_id, index),
        "PUT",
        Some(&body),
    )
    .await
}

/// Remove training class.
pub async fn remove_training_class(
    dataset_id: &str,
    index: usize,
) -> Result<ClassesResponse, String> {
    fetch_api(
        &format!("/api/v1/training/datasets/{}/classes/{}", dataset_id, index),
        "DELETE",
        None,
    )
    .await
}

/// Get sam status.
pub async fn get_sam_status() -> Result<SamStatusResponse, String> {
    fetch_api("/api/v1/training/sam", "GET", None).await
}

/// Load sam.
pub async fn load_sam() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/sam/load", "POST", Some("{}")).await
}

/// Unload sam.
pub async fn unload_sam() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/sam/unload", "POST", Some("{}")).await
}

/// Sam segment.
pub async fn sam_segment(
    dataset_id: &str,
    image_id: &str,
    text_prompt: &str,
    points: &[(f32, f32, bool)],
    threshold: f32,
) -> Result<SamSegmentResponse, String> {
    let points: Vec<serde_json::Value> = points
        .iter()
        .map(|(x, y, positive)| serde_json::json!({"x": x, "y": y, "positive": positive}))
        .collect();
    let body = serde_json::json!({
        "dataset_id": dataset_id,
        "image_id": image_id,
        "text_prompt": text_prompt,
        "points": points,
        "threshold": threshold,
    })
    .to_string();
    fetch_api("/api/v1/training/sam/segment", "POST", Some(&body)).await
}

/// Start training.
pub async fn start_training(
    dataset_id: &str,
    model_name: &str,
    epochs: u32,
    batch: u32,
    patience: u32,
) -> Result<TrainingJobStatus, String> {
    let body = serde_json::json!({
        "dataset_id": dataset_id,
        "model_name": model_name,
        "epochs": epochs,
        "batch": batch,
        "patience": patience,
    })
    .to_string();
    fetch_api("/api/v1/training/train", "POST", Some(&body)).await
}

/// Get training status.
pub async fn get_training_status() -> Result<TrainingJobStatus, String> {
    fetch_api("/api/v1/training/train/status", "GET", None).await
}

/// Cancel training.
pub async fn cancel_training() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/train/cancel", "POST", Some("{}")).await
}

/// Gracefully end the running job, keeping the best model so far (vs. cancel,
/// which discards it).
pub async fn finish_training() -> Result<SimpleResult, String> {
    fetch_api("/api/v1/training/train/finish", "POST", Some("{}")).await
}
