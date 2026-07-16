//! Detection control (HTTP/protobuf).

use prost::Message;

use crate::api::wasm32::http::fetch_protobuf;
use crate::proto::detection;

/// Start detection.
pub async fn start_detection() -> Result<(), String> {
    let request = detection::StartDetectionRequest {};
    let request_bytes = request.encode_to_vec();
    let response: detection::StartDetectionResponse =
        fetch_protobuf("/api/v1/start", "POST", Some(&request_bytes)).await?;
    if response.success {
        Ok(())
    } else {
        Err(response.message)
    }
}

/// Stop detection.
pub async fn stop_detection() -> Result<(), String> {
    let request = detection::StopDetectionRequest {};
    let request_bytes = request.encode_to_vec();
    let response: detection::StopDetectionResponse =
        fetch_protobuf("/api/v1/stop", "POST", Some(&request_bytes)).await?;
    if response.success {
        Ok(())
    } else {
        Err(response.message)
    }
}

/// Set threshold.
pub async fn set_threshold(threshold: f32) -> Result<(), String> {
    let request = detection::SetThresholdRequest { threshold };
    let request_bytes = request.encode_to_vec();
    let response: detection::SetThresholdResponse =
        fetch_protobuf("/api/v1/threshold", "POST", Some(&request_bytes)).await?;
    if response.success {
        Ok(())
    } else {
        Err(response.message)
    }
}

/// Set overlay threshold.
pub async fn set_overlay_threshold(threshold: f32) -> Result<(), String> {
    let request = detection::SetThresholdRequest { threshold };
    let request_bytes = request.encode_to_vec();
    let response: detection::SetThresholdResponse =
        fetch_protobuf("/api/v1/overlay_threshold", "POST", Some(&request_bytes)).await?;
    if response.success {
        Ok(())
    } else {
        Err(response.message)
    }
}
