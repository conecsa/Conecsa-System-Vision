//! Leptos UI components for the web frontend.

mod configuration;
mod conversion_overlay;
pub mod model_conversion;
// Public so other pages (e.g. the training label editor) can reuse the slider.
pub mod threshold_slider;

pub use configuration::Configuration;
