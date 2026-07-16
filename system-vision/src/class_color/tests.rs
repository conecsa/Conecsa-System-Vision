//! Unit tests for the `"name #hex"` class convention (headless browser).
use super::*;
use wasm_bindgen_test::*;

fn classes(entries: &[&str]) -> Vec<String> {
    entries.iter().map(|e| e.to_string()).collect()
}

#[wasm_bindgen_test]
fn short_and_long_hex_colors_are_valid() {
    assert!(is_hex_color("#fff"));
    assert!(is_hex_color("#ef4444"));
    assert!(is_hex_color("#FFAA00"));
}

#[wasm_bindgen_test]
fn malformed_hex_colors_are_rejected() {
    assert!(!is_hex_color(""));
    assert!(!is_hex_color("fff"));
    assert!(!is_hex_color("#ff"));
    assert!(!is_hex_color("#ffff"));
    assert!(!is_hex_color("#gggggg"));
    assert!(!is_hex_color("#ef44441"));
}

#[wasm_bindgen_test]
fn trailing_hex_color_is_split_from_the_name() {
    assert_eq!(
        parse_class_with_color("cap #ef4444"),
        ("cap".to_string(), Some("#ef4444".to_string()))
    );
}

#[wasm_bindgen_test]
fn multi_word_names_keep_all_words() {
    assert_eq!(
        parse_class_with_color("big red cap #fff"),
        ("big red cap".to_string(), Some("#fff".to_string()))
    );
}

#[wasm_bindgen_test]
fn name_without_color_is_kept_whole() {
    assert_eq!(parse_class_with_color("red cap"), ("red cap".to_string(), None));
}

#[wasm_bindgen_test]
fn lone_color_token_is_a_name_not_a_color() {
    assert_eq!(parse_class_with_color("#ef4444"), ("#ef4444".to_string(), None));
}

#[wasm_bindgen_test]
fn surrounding_whitespace_is_trimmed() {
    assert_eq!(
        parse_class_with_color("  cap   #fff  "),
        ("cap".to_string(), Some("#fff".to_string()))
    );
    assert_eq!(parse_class_with_color("   "), (String::new(), None));
}

#[wasm_bindgen_test]
fn a_trailing_hash_token_that_is_not_a_hex_stays_in_the_name() {
    // "#3" is not a valid hex color, so it belongs to the name.
    assert_eq!(parse_class_with_color("item #3"), ("item #3".to_string(), None));
    assert_eq!(class_display_name("item #3"), "item #3");
}

#[wasm_bindgen_test]
fn display_name_strips_the_color_suffix() {
    assert_eq!(class_display_name("person #ff0000"), "person");
    assert_eq!(class_display_name("person"), "person");
    // A bare color is the whole name — don't render an empty label.
    assert_eq!(class_display_name("#ff0000"), "#ff0000");
}

#[wasm_bindgen_test]
fn explicit_hex_wins_over_the_palette() {
    let cls = classes(&["cap #ef4444", "bottle"]);
    assert_eq!(class_color_for(0, &cls), "#ef4444");
}

#[wasm_bindgen_test]
fn short_hex_is_expanded_to_six_digits() {
    // Callers append an alpha pair ("{color}33") for the selected-box fill,
    // which is only valid CSS from a 6-digit base.
    let cls = classes(&["cap #fff"]);
    assert_eq!(class_color_for(0, &cls), "#ffffff");
}

#[wasm_bindgen_test]
fn classes_without_a_hex_fall_back_to_the_palette_by_index() {
    let cls = classes(&["cap", "bottle"]);
    assert_eq!(class_color_for(0, &cls), "#ffa500");
    assert_eq!(class_color_for(1, &cls), "#ff0000");
}

#[wasm_bindgen_test]
fn palette_fallback_is_independent_of_neighbours_colors() {
    // An explicit color on class 0 must not shift class 1's palette slot —
    // the fallback is keyed by index, not by "how many uncolored so far".
    let cls = classes(&["cap #123456", "bottle"]);
    assert_eq!(class_color_for(1, &cls), "#ff0000");
}

#[wasm_bindgen_test]
fn out_of_range_class_ids_still_get_a_color() {
    let cls = classes(&["cap"]);
    // A model reporting more classes than the list must not panic.
    assert_eq!(class_color_for(3, &cls), BASE_COLORS[3]);
}

#[wasm_bindgen_test]
fn beyond_the_base_palette_colors_are_hsv_spread() {
    // 12 classes: indices 0..9 come from the base list, 10 and 11 are
    // generated with hue = i/2 — matching generate_colors() in api/utils.py.
    let cls: Vec<String> = (0..12).map(|i| format!("c{i}")).collect();
    assert_eq!(class_color_for(9, &cls), "#808000");
    // i=0: hue 0.0, sat 0.8, val 0.9 -> pure-ish red at 90% value.
    assert_eq!(class_color_for(10, &cls), "#e52d2d");
    // i=1: hue 0.5, sat 0.9, val 1.0 -> cyan.
    assert_eq!(class_color_for(11, &cls), "#19ffff");
}
