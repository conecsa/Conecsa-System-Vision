//! Unit tests for the frontend serde models (run in a headless browser).
use super::*;
use wasm_bindgen_test::*;

wasm_bindgen_test_configure!(run_in_browser);

#[wasm_bindgen_test]
fn system_status_round_trip() {
    let status = SystemStatus {
        is_running: true,
        model: "yolo26s".into(),
        confidence_threshold: 0.75,
        overlay_threshold: 0.45,
        acceleration_type: "TensorRT".into(),
        camera_connected: true,
        stats: PerformanceStats {
            fps: 30.0,
            inference_time: 12.5,
            detections: 3,
            frames_with_detections: 100,
        },
        protocols: ProtocolInfo { http_port: 80 },
    };
    let json = serde_json::to_string(&status).unwrap();
    let back: SystemStatus = serde_json::from_str(&json).unwrap();
    assert_eq!(back.model, "yolo26s");
    assert_eq!(back.stats.fps, 30.0);
    assert_eq!(back.protocols.http_port, 80);
}

#[wasm_bindgen_test]
fn system_status_defaults_missing_acceleration_type() {
    let json = r#"{
        "is_running": false, "model": "m",
        "confidence_threshold": 0.5, "overlay_threshold": 0.4,
        "stats": {"fps": 0.0, "inference_time": 0.0, "detections": 0, "frames_with_detections": 0},
        "protocols": {}
    }"#;
    let status: SystemStatus = serde_json::from_str(json).unwrap();
    assert_eq!(status.acceleration_type, "");
    assert_eq!(status.protocols.http_port, 0); // ProtocolInfo default
    // A gateway that predates the field must not make the UI claim the camera
    // is gone (which would also disable Start Detection).
    assert!(status.camera_connected);
}

#[wasm_bindgen_test]
fn model_info_round_trip() {
    let info = ModelInfo {
        name: "weights.engine".into(),
        size: 1024,
        modified: 1_700_000_000.0,
        is_active: true,
    };
    let back: ModelInfo = serde_json::from_str(&serde_json::to_string(&info).unwrap()).unwrap();
    assert_eq!(back.name, "weights.engine");
    assert!(back.is_active);
}

#[wasm_bindgen_test]
fn detection_config_tuple_resolution() {
    let cfg = DetectionConfig {
        capture_device: "/dev/media0".into(),
        capture_resolution: (1920, 1080),
        capture_framerate: 30,
        model_path: "/data/models/weights.engine".into(),
        confidence_threshold: 0.6,
    };
    let back: DetectionConfig =
        serde_json::from_str(&serde_json::to_string(&cfg).unwrap()).unwrap();
    assert_eq!(back.capture_resolution, (1920, 1080));
}

#[wasm_bindgen_test]
fn system_metrics_optional_gpu_fields_default_to_none() {
    let json = r#"{
        "cpu_usage": 10.0, "ram_usage": 20.0, "ram_total": 100, "ram_used": 20,
        "disk_usage": 30.0, "disk_total": 200, "disk_used": 60, "temperature": 45.0
    }"#;
    let m: SystemMetrics = serde_json::from_str(json).unwrap();
    assert_eq!(m.temperature, Some(45.0));
    assert!(m.gpu_usage.is_none());
    assert!(m.gpu_temperature.is_none());
}
