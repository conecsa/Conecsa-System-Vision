//! Unit tests for the generated prost detection messages (headless browser).
use super::*;
use prost::Message;
use wasm_bindgen_test::*;

#[wasm_bindgen_test]
fn status_response_encode_decode_round_trip() {
    let msg = StatusResponse {
        is_running: true,
        current_model: "yolo26s".into(),
        confidence_threshold: 0.75,
        stats: Some(Stats {
            fps: 30.0,
            inference_time: 12.0,
            detections: 4,
            frames_with_detections: 200,
        }),
        protocols: Some(Protocols { http_port: 80 }),
        camera_connected: true,
    };
    let bytes = msg.encode_to_vec();
    let back = StatusResponse::decode(&bytes[..]).unwrap();
    assert_eq!(msg, back);
}

#[wasm_bindgen_test]
fn start_detection_response_round_trip() {
    let msg = StartDetectionResponse {
        success: true,
        message: "started".into(),
        video_feed_url: "/api/v1/video".into(),
    };
    let back = StartDetectionResponse::decode(&msg.encode_to_vec()[..]).unwrap();
    assert_eq!(msg, back);
}

#[wasm_bindgen_test]
fn default_message_encodes_to_empty() {
    // All-default scalar fields are omitted on the wire in proto3.
    let msg = StartDetectionRequest::default();
    assert!(msg.encode_to_vec().is_empty());
}

#[wasm_bindgen_test]
fn stats_round_trip_preserves_values() {
    let stats = Stats {
        fps: 24.5,
        inference_time: 8.0,
        detections: 2,
        frames_with_detections: 50,
    };
    let back = Stats::decode(&stats.encode_to_vec()[..]).unwrap();
    assert_eq!(back.fps, 24.5);
    assert_eq!(back.frames_with_detections, 50);
}
