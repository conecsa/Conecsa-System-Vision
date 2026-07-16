//! V4L2 hardware controls applied via `v4l2-ctl`: exposure, gamma, gain and
//! RGB white-balance levels, with detection of the software fallback for
//! cameras lacking per-channel balance controls.

use super::super::{CameraConfig, WebcamServer};

impl WebcamServer {
    /// Query v4l2 control range.
    fn query_v4l2_control_range(dev: &str, control: &str) -> Option<(u32, u32)> {
        let output = std::process::Command::new("v4l2-ctl")
            .args(["--device", dev, "--list-ctrls"])
            .output()
            .ok()?;

        if !output.status.success() {
            return None;
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let line = stdout
            .lines()
            .find(|line| line.trim_start().starts_with(control))?;

        let mut min_v = None;
        let mut max_v = None;
        for token in line.split_whitespace() {
            if let Some(v) = token.strip_prefix("min=") {
                min_v = v.parse::<u32>().ok();
            } else if let Some(v) = token.strip_prefix("max=") {
                max_v = v.parse::<u32>().ok();
            }
        }

        match (min_v, max_v) {
            (Some(min_v), Some(max_v)) if min_v <= max_v => Some((min_v, max_v)),
            _ => None,
        }
    }

    /// Set v4l2 control.
    fn set_v4l2_control(dev: &str, ctrl: &str) -> bool {
        match std::process::Command::new("v4l2-ctl")
            .args(["--device", dev, "--set-ctrl", ctrl])
            .output()
        {
            Ok(output) if output.status.success() => true,
            Ok(output) => {
                let err = String::from_utf8_lossy(&output.stderr);
                eprintln!("[webcam] v4l2 control failed ({ctrl}): {err}");
                false
            }
            Err(err) => {
                eprintln!("[webcam] failed to run v4l2-ctl for {ctrl}: {err}");
                false
            }
        }
    }

    pub(crate) fn apply_exposure(camera_index: u32, cfg: &CameraConfig) -> bool {
        let dev = format!("/dev/video{}", camera_index);

        let _ = Self::set_v4l2_control(&dev, "exposure_dynamic_framerate=0");

        if cfg.auto_exposure {
            let _ = Self::set_v4l2_control(&dev, "auto_exposure=3");
            eprintln!("[webcam] Exposure: auto (aperture priority)");
        } else {
            let _ = Self::set_v4l2_control(&dev, "auto_exposure=1");
            let _ = Self::set_v4l2_control(
                &dev,
                &format!("exposure_time_absolute={}", cfg.exposure_time),
            );
            eprintln!(
                "[webcam] Exposure: manual {}x100us (~{:.0}ms)",
                cfg.exposure_time,
                cfg.exposure_time as f32 * 0.1
            );
        }

        // Apply gamma if non-default.
        let _ = Self::set_v4l2_control(&dev, &format!("gamma={}", cfg.gamma));

        let gain_to_apply = if let Some((min_gain, max_gain)) = Self::query_v4l2_control_range(&dev, "gain") {
            cfg.gain.clamp(min_gain, max_gain)
        } else {
            cfg.gain
        };
        let gain_ok = Self::set_v4l2_control(&dev, &format!("gain={}", gain_to_apply));
        if gain_ok {
            eprintln!("[webcam] Gain: {}", gain_to_apply);
        }

        let mut rgb_hw_supported = true;
        if cfg.has_non_neutral_rgb_levels()
            && Self::query_v4l2_control_range(&dev, "red_balance").is_none()
        {
            // The camera exposes no red/blue balance controls (e.g. the USB
            // stereo camera, which only has white_balance_automatic). Leave
            // white balance untouched — disabling AWB without compensating R/B
            // controls would just tint the image. RGB levels are applied
            // downstream in software instead (the inference-service for MJPEG
            // passthrough; apply_software_rgb_levels for the raw/decode paths).
            rgb_hw_supported = false;
            eprintln!("[webcam] red_balance unsupported — RGB levels applied downstream in software");
        } else if cfg.has_non_neutral_rgb_levels() {
            // Disable auto white balance so red_balance/blue_balance are writable.
            let _ = Self::set_v4l2_control(&dev, "white_balance_automatic=0");
            let red_ok = Self::set_v4l2_control(&dev, &format!("red_balance={}", cfg.rgb_red));
            let blue_ok = Self::set_v4l2_control(&dev, &format!("blue_balance={}", cfg.rgb_blue));
            let green_ok = Self::set_v4l2_control(&dev, &format!("green_balance={}", cfg.rgb_green));
            if !green_ok {
                // green_balance is not supported by this driver (common on RGGB sensors).
                // Reset R/B to neutral so the hardware partial correction does not fight
                // the software path — apply_software_rgb_levels handles all three
                // channels cleanly on the debayered output.
                let _ = Self::set_v4l2_control(&dev, "red_balance=128");
                let _ = Self::set_v4l2_control(&dev, "blue_balance=128");
                rgb_hw_supported = false;
                eprintln!("[webcam] green_balance unsupported — RGB levels applied in software");
            } else {
                rgb_hw_supported = red_ok && blue_ok;
                if rgb_hw_supported {
                    eprintln!(
                        "[webcam] RGB levels applied by driver: R={} G={} B={}",
                        cfg.rgb_red, cfg.rgb_green, cfg.rgb_blue
                    );
                } else {
                    eprintln!("[webcam] RGB hardware controls unavailable; using software fallback");
                }
            }
        } else {
            // Re-enable auto white balance when at neutral levels.
            let _ = Self::set_v4l2_control(&dev, "white_balance_automatic=1");
        }

        rgb_hw_supported
    }
}
