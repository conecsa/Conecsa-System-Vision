//! Leptos UI components for the web frontend.

mod exposure_control;
mod image_adjust_overlay;
mod panel;
mod range_control;
mod rgb_control;
mod toggle_button;

pub use image_adjust_overlay::ImageAdjustOverlay;

/// Shared `panel` id for this overlay (0 = none).
const PANEL_ID: u8 = 2;
