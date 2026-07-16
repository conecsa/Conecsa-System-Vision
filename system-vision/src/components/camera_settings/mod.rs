//! Leptos UI components for the web frontend.

mod apply_button;
mod component;
mod device_select;
mod loading_state;
mod resolution_controls;
mod stereo_toggle;

pub use component::CameraSettings;

/// Preset resolutions shown in the UI.
/// Tuples: (width, height, label, aspect-ratio badge)
const RESOLUTIONS: &[(u32, u32, &str, &str)] = &[
    (640, 640, "640 × 640", "1:1"),
    (1280, 720, "1280 × 720", "16:9"),
    (1440, 1080, "1440 × 1080", "4:3"),
    (1920, 1080, "1920 × 1080", "16:9"),
];

/// A `Resolution` struct.
#[derive(Clone, Copy, PartialEq)]
struct Resolution {
    w: u32,
    h: u32,
}

type CameraFormat = (u32, u32, Vec<u32>);
