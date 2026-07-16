//! Unit tests for the usage-bar color thresholds and style clamping.
use super::*;
use wasm_bindgen_test::*;

#[wasm_bindgen_test]
fn color_thresholds_at_50_and_80() {
    assert_eq!(usage_bar_color(0.0), "var(--state-success-text)");
    assert_eq!(usage_bar_color(49.9), "var(--state-success-text)");
    assert_eq!(usage_bar_color(50.0), "var(--state-warning-text)");
    assert_eq!(usage_bar_color(79.9), "var(--state-warning-text)");
    assert_eq!(usage_bar_color(80.0), "var(--state-danger-text)");
    assert_eq!(usage_bar_color(100.0), "var(--state-danger-text)");
}

#[wasm_bindgen_test]
fn style_formats_width_with_two_decimals() {
    assert_eq!(
        usage_bar_style(42.5),
        "width: 42.50%; background-color: var(--state-success-text);"
    );
}

#[wasm_bindgen_test]
fn style_clamps_out_of_range_values() {
    assert!(usage_bar_style(-10.0).starts_with("width: 0.00%"));
    assert!(usage_bar_style(150.0).starts_with("width: 100.00%"));
}

#[wasm_bindgen_test]
fn style_maps_non_finite_values_to_zero() {
    assert!(usage_bar_style(f32::NAN).starts_with("width: 0.00%"));
    assert!(usage_bar_style(f32::INFINITY).starts_with("width: 0.00%"));
    assert!(usage_bar_style(f32::NEG_INFINITY).starts_with("width: 0.00%"));
}
