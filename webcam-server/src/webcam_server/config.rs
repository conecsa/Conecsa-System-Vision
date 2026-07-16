//! Camera configuration (index, resolution, framerate, exposure, gains) sourced
//! from environment variables and updated live via the SHM config region.

use serde::{Deserialize, Serialize};

const EXPOSURE_MIN: u32 = 1;
const EXPOSURE_MAX: u32 = 300_000;
pub const RGB_LEVEL_DEFAULT: u16 = 128;
pub const GAMMA_DEFAULT: u32 = 100;
pub const GAIN_DEFAULT: u32 = 0;

/// A `CameraConfig` struct.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CameraConfig {
    pub camera_index: u32,
    pub width: u32,
    pub height: u32,
    pub framerate: u32,
    // false = manual exposure (v4l2 auto_exposure=1)
    // true = auto/aperture-priority (v4l2 auto_exposure=3)
    pub auto_exposure: bool,
    // Exposure time in 100 us units, used only when auto_exposure = false.
    pub exposure_time: u32,
    // Software/hardware RGB levels. 128 = neutral gain.
    pub rgb_red: u16,
    pub rgb_green: u16,
    pub rgb_blue: u16,
    // Gamma correction (V4L2 gamma control, range 1–500, 100 = neutral).
    pub gamma: u32,
    // Camera analog/digital gain (V4L2 gain control).
    pub gain: u32,
    // Shared-memory segment name (without leading slash).
    #[serde(skip)]
    pub shm_name: String,
}

impl Default for CameraConfig {
    /// Default.
    fn default() -> Self {
        let framerate: u32 = std::env::var("CAPTURE_FRAMERATE")
            .unwrap_or_else(|_| "60".to_string())
            .parse()
            .unwrap_or(60);

        Self {
            camera_index: std::env::var("CAMERA_INDEX")
                .unwrap_or_else(|_| "0".to_string())
                .parse()
                .unwrap_or(0),
            width: std::env::var("CAPTURE_WIDTH")
                .unwrap_or_else(|_| "2560".to_string())
                .parse()
                .unwrap_or(2560),
            height: std::env::var("CAPTURE_HEIGHT")
                .unwrap_or_else(|_| "720".to_string())
                .parse()
                .unwrap_or(720),
            framerate,
            auto_exposure: false,
            // Default: 1/fps seconds (e.g. 333 x 100 us ~= 33 ms ~= 1/30 s)
            exposure_time: (10_000u32 / framerate.max(1)).clamp(EXPOSURE_MIN, EXPOSURE_MAX),
            rgb_red: RGB_LEVEL_DEFAULT,
            rgb_green: RGB_LEVEL_DEFAULT,
            rgb_blue: RGB_LEVEL_DEFAULT,
            gamma: GAMMA_DEFAULT,
            gain: GAIN_DEFAULT,
            shm_name: std::env::var("SHM_NAME")
                .unwrap_or_else(|_| "conecsa_frame_shm".to_string()),
        }
    }
}

impl CameraConfig {
    /// Has non neutral rgb levels.
    pub fn has_non_neutral_rgb_levels(&self) -> bool {
        self.rgb_red != RGB_LEVEL_DEFAULT
            || self.rgb_green != RGB_LEVEL_DEFAULT
            || self.rgb_blue != RGB_LEVEL_DEFAULT
    }
}

#[cfg(test)]
mod tests;

