//! Unit tests for the software image-processing helpers.
use super::super::WebcamServer;

#[test]
fn gain_zero_is_a_no_op() {
    let mut rgb = [10u8, 20, 30, 40];
    WebcamServer::apply_software_gain(&mut rgb, 0);
    assert_eq!(rgb, [10, 20, 30, 40]);
}

#[test]
fn gain_128_doubles_values() {
    // multiplier = 1.0 + 128/128 = 2.0
    let mut rgb = [10u8, 20, 30];
    WebcamServer::apply_software_gain(&mut rgb, 128);
    assert_eq!(rgb, [20, 40, 60]);
}

#[test]
fn gain_clamps_to_255() {
    let mut rgb = [200u8];
    WebcamServer::apply_software_gain(&mut rgb, 128); // 400 -> clamp 255
    assert_eq!(rgb, [255]);
}

#[test]
fn rgb_levels_scale_each_channel() {
    // r_gain = 256/128 = 2, g/b neutral (128/128 = 1).
    let mut rgb = [100u8, 100, 100];
    WebcamServer::apply_software_rgb_levels(&mut rgb, 256, 128, 128);
    assert_eq!(rgb, [200, 100, 100]);
}

#[test]
fn rgb_levels_neutral_is_identity() {
    let mut rgb = [12u8, 34, 56];
    WebcamServer::apply_software_rgb_levels(&mut rgb, 128, 128, 128);
    assert_eq!(rgb, [12, 34, 56]);
}

#[test]
fn rgb_levels_clamp_high_channel() {
    let mut rgb = [200u8, 0, 0];
    WebcamServer::apply_software_rgb_levels(&mut rgb, 255, 128, 128);
    assert_eq!(rgb[0], 255);
}

#[test]
fn debayer_output_length() {
    let raw = vec![100u8; 8 * 6];
    let rgb = WebcamServer::debayer_rggb8(&raw, 8, 6);
    assert_eq!(rgb.len(), 8 * 6 * 3);
}

#[test]
fn debayer_uniform_input_is_uniform_output() {
    // Every Bayer site has the same value, so all interpolations return it.
    let raw = vec![100u8; 8 * 6];
    let rgb = WebcamServer::debayer_rggb8(&raw, 8, 6);
    assert!(rgb.iter().all(|&v| v == 100));
}
