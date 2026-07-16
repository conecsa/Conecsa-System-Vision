//! Capture-loop orchestration: owns the camera config, the SHM producer and the
//! restart flag, and runs the acquire→process→publish loop (with camera
//! re-attach when the device is absent).

mod capture;
mod config;
mod processing;
pub mod shm;

use std::sync::{Arc, Mutex, atomic::AtomicBool};

pub use config::CameraConfig;

/// Path (in the shared `/dev/shm` tmpfs) where the supported camera formats are
/// published as JSON for the inference-service to expose through its API.
pub const CAMERA_FORMATS_PATH: &str = "/dev/shm/conecsa_camera_formats.json";

/// A `WebcamServer` struct.
pub struct WebcamServer {
    pub shm: Arc<shm::ShmProducer>,
    pub config: Arc<Mutex<CameraConfig>>,
    pub needs_restart: Arc<AtomicBool>,
    pub rgb_hardware_supported: Arc<AtomicBool>,
}

impl WebcamServer {
    /// New.
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let cfg = CameraConfig::default();
        let shm = shm::ShmProducer::new(&cfg.shm_name, cfg.width, cfg.height)
            .map_err(|e| format!("Failed to create shared memory: {e}"))?;

        eprintln!(
            "[webcam] SHM /{} created — {}x{} double-buffered",
            cfg.shm_name, cfg.width, cfg.height
        );

        Ok(Self {
            shm: Arc::new(shm),
            config: Arc::new(Mutex::new(cfg)),
            needs_restart: Arc::new(AtomicBool::new(false)),
            rgb_hardware_supported: Arc::new(AtomicBool::new(false)),
        })
    }
}

/// Run server.
pub fn run_server() -> Result<(), Box<dyn std::error::Error>> {
    let server = Arc::new(WebcamServer::new()?);

    let cfg = server.config.lock().unwrap().clone();
    eprintln!(
        "[webcam] Capture daemon started — camera {} @ {}x{} {} fps",
        cfg.camera_index, cfg.width, cfg.height, cfg.framerate
    );
    eprintln!("[webcam] Frames written to SHM /{}", cfg.shm_name);
    drop(cfg);

    // Enumerate supported camera formats once, before the capture loop opens
    // (and locks) the device. Shared with the inference-service via /dev/shm.
    WebcamServer::write_camera_formats_json(CAMERA_FORMATS_PATH);

    // Run capture loop on the current thread (blocking).
    server.start_capture_loop();

    Ok(())
}
