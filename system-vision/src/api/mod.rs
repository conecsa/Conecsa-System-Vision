//! Backend access layer (HTTP/SSE).

/// Parse classes text.
pub fn parse_classes_text(text: &str) -> Vec<String> {
    text.lines()
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .collect()
}

// ── service module ────────────────────────────────────────────────────────────

pub mod wasm32;

// ── re-exports ────────────────────────────────────────────────────────────────

pub use wasm32::http::fetch_api;

pub use wasm32::services::detection::{
    set_overlay_threshold, set_threshold, start_detection, stop_detection,
};

pub use wasm32::services::model::{
    delete_model, get_conversion_status, list_active_conversions, model_download_url,
    select_model, upload_model_dialog, upload_model_file, ActiveConversionsResponse,
    ConversionStatusResponse, UploadModelResponse,
};

pub use wasm32::services::classes::{
    clear_classes, get_classes, upload_classes, upload_classes_dialog, upload_classes_file,
};

pub use wasm32::services::camera::{
    get_camera_devices, update_camera_config, update_stereo_config, CameraDevice,
    CameraDevicesResponse,
};

pub use wasm32::services::detection_areas::{
    create_detection_area, delete_detection_area, discard_detection_area, edit_detection_area,
    list_detection_areas, save_detection_area, send_area_command, set_area_shape, DetectionArea,
    DetectionAreasResponse,
};

pub use wasm32::services::system::get_system_metrics;

pub use wasm32::services::network::{
    connect_wifi, forget_wifi, get_network_config, scan_wifi, set_network_config, InterfaceConfig,
    NetworkConfig, NetworkSetResponse, WifiConnectResponse, WifiNetwork, WifiScanResponse,
    WifiStatus,
};

pub use wasm32::services::gpio::{
    get_gpio_status, set_gpio_trigger, GpioStatus, GpioTriggerResponse,
};

pub use wasm32::services::power::{system_power, SystemPowerResponse};

pub use wasm32::services::event_stream::{subscribe_app_events, AppEvent, AppEventStreamHandle};

pub use wasm32::services::training::{
    add_training_class, cancel_training, capture_training_image, create_dataset, delete_dataset,
    delete_training_image, finish_training, get_sam_status, get_training_classes, get_training_dataset,
    get_training_labels, get_training_status, list_datasets, list_training_images, load_sam,
    remove_training_class, rename_dataset, rename_training_class, replicate_training_image,
    sam_segment, set_dataset_cover,
    set_training_labels, start_training, training_dataset_export_url, training_enter,
    training_exit, training_heartbeat, training_image_url, training_preview_url,
    upload_dataset_zip, DatasetSummary,
    LabelBox, SamStatusResponse, TrainingDatasetInfo, TrainingImageInfo, TrainingJobStatus,
};

#[cfg(test)]
mod tests;
