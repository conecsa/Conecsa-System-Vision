//! webcam-server — the Rust camera capture process.
//!
//! Captures frames from a V4L2 device (native MJPEG passthrough, RGGB8 Bayer
//! debayering, or a YUYV fallback) and publishes them to a POSIX shared-memory
//! ring (`SHM_NAME`) for the inference-service and api-gateway to consume — no
//! HTTP. When no camera is present it publishes no frames at all — only the
//! `no_camera` health status, which gates detection downstream — and keeps
//! re-attempting the real device, so a re-plugged camera self-heals.
//!
//! See [`webcam_server`] for the capture loop and [`webcam_server::shm`] for the
//! shared-memory producer.

mod webcam_server;

/// Initialise logging and run the capture loop until the process is killed.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::init();
    webcam_server::run_server()
}
