//! Leptos UI components for the web frontend.

use serde::{Deserialize, Serialize};

mod metric_card;
mod metrics_grid;
mod status_component;

pub use status_component::StatusComponent;

/// A `SystemMetrics` struct.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SystemMetrics {
    pub cpu_usage: f32,
    pub ram_usage: f32,
    pub ram_total: u64,
    pub ram_used: u64,
    pub disk_usage: f32,
    pub disk_total: u64,
    pub disk_used: u64,
    pub temperature: Option<f32>,
    pub gpu_usage: Option<f32>,
    pub gpu_temperature: Option<f32>,
    pub gpu_freq_mhz: Option<f32>,
    pub gpu_max_freq_mhz: Option<f32>,
}
