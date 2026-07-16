//! Unit tests for the pure classes-text parser.
use super::*;
use wasm_bindgen_test::*;

#[wasm_bindgen_test]
fn splits_one_class_per_line() {
    assert_eq!(parse_classes_text("person\ncar\ndog"), vec!["person", "car", "dog"]);
}

#[wasm_bindgen_test]
fn trims_whitespace_around_each_class() {
    assert_eq!(parse_classes_text("  person \n\tcar\t"), vec!["person", "car"]);
}

#[wasm_bindgen_test]
fn drops_blank_and_whitespace_only_lines() {
    assert_eq!(parse_classes_text("person\n\n   \ncar\n"), vec!["person", "car"]);
}

#[wasm_bindgen_test]
fn handles_crlf_line_endings() {
    assert_eq!(parse_classes_text("person\r\ncar\r\n"), vec!["person", "car"]);
}

#[wasm_bindgen_test]
fn empty_or_whitespace_input_yields_no_classes() {
    assert!(parse_classes_text("").is_empty());
    assert!(parse_classes_text(" \n\t\n").is_empty());
}
