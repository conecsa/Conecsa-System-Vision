//! Direct V4L2 capture paths (bypassing nokhwa): MJPEG passthrough and raw
//! Bayer/greyscale capture loops.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use v4l::buffer::Type;
use v4l::io::traits::CaptureStream;
use v4l::prelude::*;
use v4l::video::Capture;

use super::super::shm::ShmProducer;
use super::super::{CameraConfig, WebcamServer};

impl WebcamServer {
    pub(crate) fn try_v4l2_raw_loop(
        dev_path: &str,
        cfg: &CameraConfig,
        shm: &Arc<ShmProducer>,
        shm_poll: &Arc<ShmProducer>,
        config_arc: &std::sync::Arc<std::sync::Mutex<CameraConfig>>,
        restart_flag: &AtomicBool,
        rgb_hardware_supported: &AtomicBool,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let dev = v4l::Device::with_path(dev_path)?;
        let mut fmt = dev.format()?;
        eprintln!(
            "[webcam] V4L2 raw: {}x{} fourcc={:?}",
            fmt.width, fmt.height, fmt.fourcc
        );

        fmt.width = cfg.width;
        fmt.height = cfg.height;
        let fmt = dev.set_format(&fmt).unwrap_or_else(|_| dev.format().unwrap());

        let w = fmt.width as usize;
        let h = fmt.height as usize;
        eprintln!("[webcam] V4L2 raw: negotiated {}x{}", w, h);

        let fourcc_str = std::str::from_utf8(&fmt.fourcc.repr)
            .unwrap_or("????")
            .trim_end_matches('\0')
            .to_uppercase();
        let is_rggb = fourcc_str.contains("RGGB") || fourcc_str.contains("BA81");

        let mut stream = MmapStream::with_buffers(&dev, Type::VideoCapture, 4)?;
        eprintln!("[webcam] V4L2 raw: stream opened (fourcc={})", fourcc_str);
        let rgb_hw = Self::apply_exposure(cfg.camera_index, cfg);
        rgb_hardware_supported.store(rgb_hw, Ordering::Relaxed);

        Self::publish_health(&shm, cfg, "capturing");

        loop {
            if restart_flag.load(Ordering::Relaxed) {
                break;
            }
            // Poll for config changes from consumer.
            let shm_mut = unsafe {
                &mut *(Arc::as_ptr(shm_poll) as *mut ShmProducer)
            };
            if let Some(proto_cfg) = shm_mut.poll_config() {
                Self::apply_shm_config(
                    &proto_cfg,
                    config_arc,
                    &shm,
                    restart_flag,
                    rgb_hardware_supported,
                );
            }
            // Re-read config to pick up any changes.
            let current_cfg = config_arc.lock().unwrap().clone();
            let use_software_rgb = current_cfg.has_non_neutral_rgb_levels()
                && !rgb_hardware_supported.load(Ordering::Relaxed);

            let (buf, _meta) = stream.next()?;
            let rgb = if is_rggb {
                Self::debayer_rggb8(buf, w, h)
            } else {
                let mut rgb = vec![0u8; w * h * 3];
                for (i, &v) in buf.iter().take(w * h).enumerate() {
                    rgb[i * 3] = v;
                    rgb[i * 3 + 1] = v;
                    rgb[i * 3 + 2] = v;
                }
                rgb
            };
            let mut rgb = rgb;
            // Hardware gain has no effect on raw sensor output; apply in software.
            if is_rggb {
                Self::apply_software_gain(&mut rgb, current_cfg.gain);
            }
            if use_software_rgb {
                Self::apply_software_rgb_levels(
                    &mut rgb,
                    current_cfg.rgb_red,
                    current_cfg.rgb_green,
                    current_cfg.rgb_blue,
                );
            }
            shm.publish_frame_rgb(&rgb, w as u32, h as u32);
        }

        Ok(())
    }

    /// Return the byte length of the actual JPEG payload inside `buf`.
    ///
    /// V4L2/nokhwa buffers are allocated to the format's full `sizeimage`, so a
    /// compressed MJPEG frame leaves a large zero/garbage tail. Publishing the
    /// whole buffer wastes ~16× the bandwidth (8 MB vs ~0.5 MB) and forces the
    /// consumer to copy and scan it. Trim to the trailing `FF D9` (EOI) marker.
    pub(crate) fn jpeg_payload_len(buf: &[u8]) -> usize {
        match buf.windows(2).rposition(|w| w == [0xFF, 0xD9]) {
            Some(pos) => pos + 2,
            None => buf.len(),
        }
    }

    /// Capture MJPEG directly through the `v4l` crate (bypassing nokhwa).
    ///
    /// This is the primary path for MJPEG cameras because it gives us:
    ///   1. explicit frame-interval control (`set_params`) so we capture at the
    ///      requested fps instead of nokhwa's negotiated default (which capped
    ///      this stereo camera at 30 fps), and
    ///   2. the real JPEG length via `Metadata.bytesused`, so we publish ~0.5 MB
    ///      instead of the full `sizeimage` buffer.
    ///
    /// Returns `Err` (so the caller falls back to the nokhwa / raw paths) when
    /// the device cannot deliver MJPEG at the requested format, or when software
    /// RGB levels are requested (which require decoded pixels this path lacks).
    pub(crate) fn try_v4l2_mjpeg_loop(
        dev_path: &str,
        cfg: &CameraConfig,
        shm: &Arc<ShmProducer>,
        shm_poll: &Arc<ShmProducer>,
        config_arc: &std::sync::Arc<std::sync::Mutex<CameraConfig>>,
        restart_flag: &AtomicBool,
        rgb_hardware_supported: &AtomicBool,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let dev = v4l::Device::with_path(dev_path)?;

        // Request MJPG at the configured resolution.
        let mut fmt = dev.format()?;
        fmt.width = cfg.width;
        fmt.height = cfg.height;
        fmt.fourcc = v4l::format::FourCC::new(b"MJPG");
        let fmt = dev.set_format(&fmt)?;
        if &fmt.fourcc.repr != b"MJPG" {
            return Err(format!(
                "device did not accept MJPG (got {})",
                std::str::from_utf8(&fmt.fourcc.repr).unwrap_or("????")
            )
            .into());
        }

        // Apply exposure/gamma/gain in hardware. RGB levels are applied
        // downstream by the inference-service on the decoded frame (this camera
        // has no red/blue balance controls), so passthrough stays fast and we
        // never bail to the slow nokhwa decode path for a colour change.
        let rgb_hw = Self::apply_exposure(cfg.camera_index, cfg);
        rgb_hardware_supported.store(rgb_hw, Ordering::Relaxed);

        // Explicit frame interval → capture at the requested fps.
        match dev.set_params(&v4l::video::capture::Parameters::with_fps(cfg.framerate)) {
            Ok(p) => eprintln!(
                "[webcam] V4L2 MJPEG: {}x{} interval {} ({} fps requested)",
                fmt.width, fmt.height, p.interval, cfg.framerate
            ),
            Err(e) => eprintln!("[webcam] V4L2 MJPEG: set fps failed: {e}"),
        }

        let mut stream = MmapStream::with_buffers(&dev, Type::VideoCapture, 4)?;
        eprintln!(
            "[webcam] Camera {} opened - MJPEG passthrough mode (V4L2)",
            cfg.camera_index
        );
        Self::publish_health(shm, cfg, "capturing");

        loop {
            if restart_flag.load(Ordering::Relaxed) {
                break;
            }
            // Poll for config changes from consumer.
            // SAFETY: single writer thread, poll_config uses atomics.
            let shm_mut = unsafe { &mut *(Arc::as_ptr(shm_poll) as *mut ShmProducer) };
            if let Some(proto_cfg) = shm_mut.poll_config() {
                Self::apply_shm_config(
                    &proto_cfg,
                    config_arc,
                    shm,
                    restart_flag,
                    rgb_hardware_supported,
                );
            }
            let (buf, meta) = stream.next()?;
            let used = (meta.bytesused as usize).min(buf.len());
            if used > 0 {
                shm.publish_frame_jpeg(&buf[..used]);
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests;
