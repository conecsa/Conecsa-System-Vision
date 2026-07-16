//! Capture orchestration: nokhwa camera open/decode paths and the main
//! acquire→process→publish loop, with camera re-attach when the device is
//! absent. The direct V4L2 paths live in `v4l2`, the `v4l2-ctl` hardware
//! controls in `controls` and the format enumeration in `formats`.

mod controls;
mod formats;
mod v4l2;

use nokhwa::{
    pixel_format::RgbFormat,
    utils::{
        CameraFormat, CameraIndex, FrameFormat, RequestedFormat, RequestedFormatType, Resolution,
    },
    Camera,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use super::shm::{self, ShmProducer};
use super::{CameraConfig, WebcamServer};

impl WebcamServer {
    pub(crate) fn try_open_camera(cfg: &CameraConfig) -> Result<Camera, Box<dyn std::error::Error>> {
        let index = CameraIndex::Index(cfg.camera_index);
        let resolution = Resolution::new(cfg.width, cfg.height);

        let fmt_exact = CameraFormat::new(resolution, FrameFormat::MJPEG, cfg.framerate);
        let req_exact = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Exact(fmt_exact));
        if let Ok(mut cam) = Camera::new(CameraIndex::Index(cfg.camera_index), req_exact) {
            if cam.open_stream().is_ok() {
                eprintln!(
                    "[webcam] Opened with Exact MJPEG {}x{} @ {}fps",
                    cfg.width, cfg.height, cfg.framerate
                );
                return Ok(cam);
            }
        }

        let req_hfr =
            RequestedFormat::new::<RgbFormat>(RequestedFormatType::HighestFrameRate(cfg.framerate));
        if let Ok(mut cam) = Camera::new(CameraIndex::Index(cfg.camera_index), req_hfr) {
            if cam.open_stream().is_ok() {
                eprintln!("[webcam] Opened with HighestFrameRate");
                return Ok(cam);
            }
        }

        let f_yuyv = CameraFormat::new(resolution, FrameFormat::YUYV, cfg.framerate);
        let r_yuyv = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Closest(f_yuyv));
        if let Ok(mut cam) = Camera::new(CameraIndex::Index(cfg.camera_index), r_yuyv) {
            if cam.open_stream().is_ok() {
                eprintln!("[webcam] Opened with YUYV fallback");
                return Ok(cam);
            }
        }

        let fmt_close = CameraFormat::new(resolution, FrameFormat::MJPEG, cfg.framerate);
        let req_close = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Closest(fmt_close));
        let mut camera = Camera::new(index, req_close)?;
        camera.open_stream()?;
        eprintln!("[webcam] Opened with Closest MJPEG fallback");
        Ok(camera)
    }

    /// Apply a protobuf CameraConfig received from the consumer to the
    /// in-memory config, optionally triggering a restart.
    fn apply_shm_config(
        proto_cfg: &shm::proto::CameraConfig,
        config: &std::sync::Mutex<CameraConfig>,
        shm: &ShmProducer,
        restart_flag: &AtomicBool,
        rgb_hardware_supported: &AtomicBool,
    ) {
        let mut cfg = config.lock().unwrap();
        let needs_restart = proto_cfg.camera_index != cfg.camera_index
            || proto_cfg.width != cfg.width
            || proto_cfg.height != cfg.height
            || proto_cfg.framerate != cfg.framerate;

        cfg.camera_index = proto_cfg.camera_index;
        cfg.width = proto_cfg.width;
        cfg.height = proto_cfg.height;
        cfg.framerate = proto_cfg.framerate;
        cfg.auto_exposure = proto_cfg.auto_exposure;
        cfg.exposure_time = proto_cfg.exposure_time;
        cfg.rgb_red = proto_cfg.rgb_red as u16;
        cfg.rgb_green = proto_cfg.rgb_green as u16;
        cfg.rgb_blue = proto_cfg.rgb_blue as u16;
        cfg.gamma = proto_cfg.gamma;
        cfg.gain = proto_cfg.gain;

        if needs_restart {
            eprintln!("[webcam] SHM config change requires restart");
            restart_flag.store(true, Ordering::Relaxed);
        } else {
            let rgb_hw = Self::apply_exposure(cfg.camera_index, &cfg);
            rgb_hardware_supported.store(rgb_hw, Ordering::Relaxed);
            Self::publish_health(shm, &cfg, "capturing");
        }
    }

    /// Publish health.
    fn publish_health(shm: &ShmProducer, _cfg: &CameraConfig, status: &str) {
        shm.publish_health(&shm::proto::HealthStatus {
            status: status.to_string(),
        });
    }

    /// Main capture loop — runs on the calling thread (blocking).
    pub fn start_capture_loop(self: Arc<Self>) {
        let shm = self.shm.clone();
        let config_arc = self.config.clone();
        let restart_flag = self.needs_restart.clone();
        let rgb_hardware_supported = self.rgb_hardware_supported.clone();

        // We need a mutable reference to poll_config, so use a separate clone.
        // The ShmProducer interior is mmap'd and uses atomics, so we cast away
        // the Arc for the config polling (single-thread only).
        let shm_poll = Arc::clone(&shm);

        // Track the last error logged by the retry loop so a persistently
        // unavailable camera doesn't spam the same message every retry cycle.
        let mut last_error: Option<String> = None;

        loop {
            let cfg = config_arc.lock().unwrap().clone();
            restart_flag.store(false, Ordering::Relaxed);

            eprintln!(
                "[webcam] Opening camera {} @ {}x{} {} fps",
                cfg.camera_index, cfg.width, cfg.height, cfg.framerate
            );

            Self::publish_health(&shm, &cfg, "starting");

            // Primary path: V4L2 MJPEG passthrough — correct fps + real JPEG
            // size. Returns Ok(()) only when a restart was requested (re-loop);
            // on Err we fall back to the nokhwa / raw-sensor paths below.
            let dev_path = format!("/dev/video{}", cfg.camera_index);
            match Self::try_v4l2_mjpeg_loop(
                &dev_path,
                &cfg,
                &shm,
                &shm_poll,
                &config_arc,
                &restart_flag,
                &rgb_hardware_supported,
            ) {
                Ok(()) => {
                    last_error = None;
                    continue;
                }
                Err(e) => {
                    let msg = format!("[webcam] V4L2 MJPEG path unavailable ({e}); falling back");
                    if last_error.as_deref() != Some(msg.as_str()) {
                        eprintln!("{msg}");
                        last_error = Some(msg);
                    }
                }
            }

            let camera_result = Self::try_open_camera(&cfg);

            match camera_result {
                Ok(mut cam) => {
                    last_error = None;
                    let rgb_hw = Self::apply_exposure(cfg.camera_index, &cfg);
                    rgb_hardware_supported.store(rgb_hw, Ordering::Relaxed);
                    let use_software_rgb = cfg.has_non_neutral_rgb_levels() && !rgb_hw;
                    let is_mjpeg = cam.camera_format().format() == FrameFormat::MJPEG;
                    eprintln!(
                        "[webcam] Camera {} opened - {} mode",
                        cfg.camera_index,
                        if is_mjpeg && !use_software_rgb {
                            "MJPEG passthrough"
                        } else {
                            "RGB decode"
                        }
                    );

                    Self::publish_health(&shm, &cfg, "capturing");

                    if is_mjpeg && !use_software_rgb {
                        // MJPEG passthrough — publish JPEG directly to SHM.
                        loop {
                            if restart_flag.load(Ordering::Relaxed) {
                                break;
                            }
                            // Poll for config changes from consumer.
                            // SAFETY: single writer thread, poll_config uses atomics.
                            let shm_mut = unsafe {
                                &mut *(Arc::as_ptr(&shm_poll) as *mut ShmProducer)
                            };
                            if let Some(proto_cfg) = shm_mut.poll_config() {
                                Self::apply_shm_config(
                                    &proto_cfg,
                                    &config_arc,
                                    &shm,
                                    &restart_flag,
                                    &rgb_hardware_supported,
                                );
                            }
                            if let Ok(frame) = cam.frame() {
                                let buf = frame.buffer();
                                shm.publish_frame_jpeg(&buf[..Self::jpeg_payload_len(buf)]);
                            }
                        }
                    } else {
                        // RGB decode path — no JPEG encoding needed.
                        loop {
                            if restart_flag.load(Ordering::Relaxed) {
                                break;
                            }
                            // Poll for config changes from consumer.
                            let shm_mut = unsafe {
                                &mut *(Arc::as_ptr(&shm_poll) as *mut ShmProducer)
                            };
                            if let Some(proto_cfg) = shm_mut.poll_config() {
                                Self::apply_shm_config(
                                    &proto_cfg,
                                    &config_arc,
                                    &shm,
                                    &restart_flag,
                                    &rgb_hardware_supported,
                                );
                            }
                            // Re-read config to pick up any changes.
                            let current_cfg = config_arc.lock().unwrap().clone();
                            let use_software_rgb = current_cfg.has_non_neutral_rgb_levels()
                                && !rgb_hardware_supported.load(Ordering::Relaxed);
                            if let Ok(frame) = cam.frame() {
                                if let Ok(img) = frame.decode_image::<RgbFormat>() {
                                    let w = img.width();
                                    let h = img.height();
                                    let mut raw = img.into_raw();
                                    if use_software_rgb {
                                        Self::apply_software_rgb_levels(
                                            &mut raw,
                                            current_cfg.rgb_red,
                                            current_cfg.rgb_green,
                                            current_cfg.rgb_blue,
                                        );
                                    }
                                    shm.publish_frame_rgb(&raw, w, h);
                                }
                            }
                        }
                    }
                }
                Err(_e) => {
                    let dev_path = format!("/dev/video{}", cfg.camera_index);
                    match Self::try_v4l2_raw_loop(
                        &dev_path,
                        &cfg,
                        &shm,
                        &shm_poll,
                        &config_arc,
                        &restart_flag,
                        &rgb_hardware_supported,
                    ) {
                        Ok(()) => {
                            last_error = None;
                        }
                        Err(e2) => {
                            let msg = format!(
                                "[webcam] Camera {} V4L2 raw also failed ({e2}). No camera.",
                                cfg.camera_index
                            );
                            if last_error.as_deref() != Some(msg.as_str()) {
                                eprintln!("{msg}");
                                last_error = Some(msg);
                            }
                            // Publish NO frames — consumers must see the absence
                            // of a camera, not a synthetic image (a test pattern
                            // used to be served here, and the model detected it).
                            // "no_camera" is what gates detection downstream.
                            Self::publish_health(&shm, &cfg, "no_camera");

                            // Idle briefly, then break so the outer capture loop
                            // re-attempts the real camera. Lets a reconnected /
                            // re-powered camera self-heal without restarting
                            // webcam-server (and therefore without restarting
                            // inference, which shares the SHM).
                            let retry_at =
                                std::time::Instant::now() + std::time::Duration::from_secs(5);
                            loop {
                                if restart_flag.load(Ordering::Relaxed)
                                    || std::time::Instant::now() >= retry_at
                                {
                                    break;
                                }
                                // Poll for config changes.
                                let shm_mut = unsafe {
                                    &mut *(Arc::as_ptr(&shm_poll) as *mut ShmProducer)
                                };
                                if let Some(proto_cfg) = shm_mut.poll_config() {
                                    Self::apply_shm_config(
                                        &proto_cfg,
                                        &config_arc,
                                        &shm,
                                        &restart_flag,
                                        &rgb_hardware_supported,
                                    );
                                    // apply_shm_config reports "capturing" when the
                                    // change needs no restart; there is still no
                                    // camera here, so restore the real status.
                                    if !restart_flag.load(Ordering::Relaxed) {
                                        Self::publish_health(&shm, &cfg, "no_camera");
                                    }
                                }
                                std::thread::sleep(std::time::Duration::from_millis(100));
                            }
                        }
                    }
                }
            }
        }
    }
}
