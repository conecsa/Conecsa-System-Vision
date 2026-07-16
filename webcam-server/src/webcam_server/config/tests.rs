//! Unit tests for `CameraConfig`.
use super::*;

#[test]
fn default_has_neutral_rgb_levels() {
    let cfg = CameraConfig::default();
    assert_eq!(cfg.rgb_red, RGB_LEVEL_DEFAULT);
    assert_eq!(cfg.rgb_green, RGB_LEVEL_DEFAULT);
    assert_eq!(cfg.rgb_blue, RGB_LEVEL_DEFAULT);
    assert!(!cfg.has_non_neutral_rgb_levels());
}

#[test]
fn any_off_neutral_channel_is_detected() {
    let mut cfg = CameraConfig::default();
    cfg.rgb_red = 200;
    assert!(cfg.has_non_neutral_rgb_levels());

    let mut cfg = CameraConfig::default();
    cfg.rgb_green = 0;
    assert!(cfg.has_non_neutral_rgb_levels());

    let mut cfg = CameraConfig::default();
    cfg.rgb_blue = RGB_LEVEL_DEFAULT + 1;
    assert!(cfg.has_non_neutral_rgb_levels());
}

#[test]
fn serde_round_trip_preserves_fields() {
    let mut cfg = CameraConfig::default();
    cfg.camera_index = 2;
    cfg.width = 1280;
    cfg.height = 480;
    cfg.framerate = 30;
    cfg.auto_exposure = true;
    cfg.exposure_time = 500;
    cfg.rgb_red = 140;
    cfg.gamma = 120;
    cfg.gain = 64;

    let json = serde_json::to_string(&cfg).unwrap();
    let back: CameraConfig = serde_json::from_str(&json).unwrap();

    assert_eq!(back.camera_index, 2);
    assert_eq!(back.width, 1280);
    assert_eq!(back.height, 480);
    assert_eq!(back.framerate, 30);
    assert!(back.auto_exposure);
    assert_eq!(back.exposure_time, 500);
    assert_eq!(back.rgb_red, 140);
    assert_eq!(back.gamma, 120);
    assert_eq!(back.gain, 64);
}

#[test]
fn shm_name_is_not_serialized() {
    let cfg = CameraConfig::default();
    let json = serde_json::to_string(&cfg).unwrap();
    assert!(!json.contains("shm_name"));
}
