//! Serde data structures shared across the frontend (status, models, stats, …).

use serde::{Deserialize, Serialize};

/// System status information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemStatus {
    pub is_running: bool,
    pub model: String,
    pub confidence_threshold: f32,
    pub overlay_threshold: f32,
    #[serde(default)]
    pub acceleration_type: String,
    /// False while the webcam-server reports no streaming camera: detection
    /// cannot be started and the stream shows the disconnected placeholder.
    /// Defaults to true so a gateway that predates the field never makes the
    /// UI claim the camera is gone.
    #[serde(default = "camera_connected_default")]
    pub camera_connected: bool,
    pub stats: PerformanceStats,
    pub protocols: ProtocolInfo,
}

fn camera_connected_default() -> bool {
    true
}

/// Performance statistics
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PerformanceStats {
    pub fps: f32,
    pub inference_time: f32,
    pub detections: u32,
    pub frames_with_detections: u64,
}

/// Protocol information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProtocolInfo {
    #[serde(default)]
    pub http_port: u16,
}

/// Model metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub name: String,
    pub size: u64,
    pub modified: f64,
    pub is_active: bool,
}

/// Configuration for the detection system
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DetectionConfig {
    pub capture_device: String,
    pub capture_resolution: (u32, u32),
    pub capture_framerate: u32,
    pub model_path: String,
    pub confidence_threshold: f32,
}

/// System metrics (CPU, RAM, Disk, Temperature)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemMetrics {
    pub cpu_usage: f32,
    pub ram_usage: f32,
    pub ram_total: u64,
    pub ram_used: u64,
    pub disk_usage: f32,
    pub disk_total: u64,
    pub disk_used: u64,
    pub temperature: Option<f32>,
    #[serde(default)]
    pub gpu_usage: Option<f32>,
    #[serde(default)]
    pub gpu_temperature: Option<f32>,
    #[serde(default)]
    pub gpu_freq_mhz: Option<f32>,
    #[serde(default)]
    pub gpu_max_freq_mhz: Option<f32>,
}

#[cfg(test)]
mod tests;
