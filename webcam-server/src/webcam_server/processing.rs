//! Software image processing: luminance gain, per-channel RGB levels and
//! Bayer debayering.

use super::WebcamServer;
use super::config::RGB_LEVEL_DEFAULT;

impl WebcamServer {
    /// Uniform brightness gain for cameras whose hardware gain control does not
    /// affect raw output (e.g. RGGB raw sensors).
    ///
    /// Effective multiplier: `multiplier = 1.0 + gain / 128.0`.
    /// Typical range (from API/UI): `gain = 0` → 1.0× (no change, matches V4L2 default),
    ///                               `gain = 128` → 2.0×, `gain = 255` → ~2.99×,
    ///                               `gain = 480` → ~4.75×.
    pub(crate) fn apply_software_gain(rgb: &mut [u8], gain: u32) {
        if gain == 0 {
            return;
        }
        let multiplier = 1.0 + gain as f32 / 128.0;
        for v in rgb.iter_mut() {
            *v = ((*v as f32 * multiplier).clamp(0.0, 255.0)) as u8;
        }
    }

    pub(crate) fn apply_software_rgb_levels(rgb: &mut [u8], red: u16, green: u16, blue: u16) {
        let r_gain = red as f32 / RGB_LEVEL_DEFAULT as f32;
        let g_gain = green as f32 / RGB_LEVEL_DEFAULT as f32;
        let b_gain = blue as f32 / RGB_LEVEL_DEFAULT as f32;

        for px in rgb.chunks_exact_mut(3) {
            px[0] = ((px[0] as f32 * r_gain).clamp(0.0, 255.0)) as u8;
            px[1] = ((px[1] as f32 * g_gain).clamp(0.0, 255.0)) as u8;
            px[2] = ((px[2] as f32 * b_gain).clamp(0.0, 255.0)) as u8;
        }
    }

    // Simple bilinear Bayer RGGB8 -> RGB24 debayer.
    pub(crate) fn debayer_rggb8(raw: &[u8], width: usize, height: usize) -> Vec<u8> {
        let mut rgb = vec![0u8; width * height * 3];
        let get = |x: usize, y: usize| -> u8 {
            if x < width && y < height {
                raw[y * width + x]
            } else {
                0
            }
        };

        for y in 0..height {
            for x in 0..width {
                let out = &mut rgb[(y * width + x) * 3..][..3];
                let is_even_row = y % 2 == 0;
                let is_even_col = x % 2 == 0;

                let (r, g, b) = match (is_even_row, is_even_col) {
                    (true, true) => {
                        let gsum: u16 = [
                            (x > 0).then(|| get(x - 1, y) as u16).unwrap_or(0),
                            (x + 1 < width).then(|| get(x + 1, y) as u16).unwrap_or(0),
                            (y > 0).then(|| get(x, y - 1) as u16).unwrap_or(0),
                            (y + 1 < height).then(|| get(x, y + 1) as u16).unwrap_or(0),
                        ]
                        .iter()
                        .sum();
                        let gcnt = (x > 0) as u16
                            + (x + 1 < width) as u16
                            + (y > 0) as u16
                            + (y + 1 < height) as u16;
                        let g = if gcnt > 0 { (gsum / gcnt) as u8 } else { 0 };

                        let bsum: u16 = [
                            (x > 0 && y > 0).then(|| get(x - 1, y - 1) as u16).unwrap_or(0),
                            (x + 1 < width && y > 0)
                                .then(|| get(x + 1, y - 1) as u16)
                                .unwrap_or(0),
                            (x > 0 && y + 1 < height)
                                .then(|| get(x - 1, y + 1) as u16)
                                .unwrap_or(0),
                            (x + 1 < width && y + 1 < height)
                                .then(|| get(x + 1, y + 1) as u16)
                                .unwrap_or(0),
                        ]
                        .iter()
                        .sum();
                        let bcnt = ((x > 0 && y > 0) as u16)
                            + ((x + 1 < width && y > 0) as u16)
                            + ((x > 0 && y + 1 < height) as u16)
                            + ((x + 1 < width && y + 1 < height) as u16);
                        let b = if bcnt > 0 { (bsum / bcnt) as u8 } else { 0 };
                        (get(x, y), g, b)
                    }
                    (true, false) => {
                        let g = get(x, y);
                        let rsum = (x > 0).then(|| get(x - 1, y) as u16).unwrap_or(0)
                            + (x + 1 < width).then(|| get(x + 1, y) as u16).unwrap_or(0);
                        let rcnt = (x > 0) as u16 + (x + 1 < width) as u16;
                        let r = if rcnt > 0 { (rsum / rcnt) as u8 } else { 0 };

                        let bsum = (y > 0).then(|| get(x, y - 1) as u16).unwrap_or(0)
                            + (y + 1 < height).then(|| get(x, y + 1) as u16).unwrap_or(0);
                        let bcnt = (y > 0) as u16 + (y + 1 < height) as u16;
                        let b = if bcnt > 0 { (bsum / bcnt) as u8 } else { 0 };
                        (r, g, b)
                    }
                    (false, true) => {
                        let g = get(x, y);
                        let bsum = (x > 0).then(|| get(x - 1, y) as u16).unwrap_or(0)
                            + (x + 1 < width).then(|| get(x + 1, y) as u16).unwrap_or(0);
                        let bcnt = (x > 0) as u16 + (x + 1 < width) as u16;
                        let b = if bcnt > 0 { (bsum / bcnt) as u8 } else { 0 };

                        let rsum = (y > 0).then(|| get(x, y - 1) as u16).unwrap_or(0)
                            + (y + 1 < height).then(|| get(x, y + 1) as u16).unwrap_or(0);
                        let rcnt = (y > 0) as u16 + (y + 1 < height) as u16;
                        let r = if rcnt > 0 { (rsum / rcnt) as u8 } else { 0 };
                        (r, g, b)
                    }
                    (false, false) => {
                        let bv = get(x, y);
                        let gsum: u16 = [
                            (x > 0).then(|| get(x - 1, y) as u16).unwrap_or(0),
                            (x + 1 < width).then(|| get(x + 1, y) as u16).unwrap_or(0),
                            (y > 0).then(|| get(x, y - 1) as u16).unwrap_or(0),
                            (y + 1 < height).then(|| get(x, y + 1) as u16).unwrap_or(0),
                        ]
                        .iter()
                        .sum();
                        let gcnt = (x > 0) as u16
                            + (x + 1 < width) as u16
                            + (y > 0) as u16
                            + (y + 1 < height) as u16;
                        let g = if gcnt > 0 { (gsum / gcnt) as u8 } else { 0 };

                        let rsum: u16 = [
                            (x > 0 && y > 0).then(|| get(x - 1, y - 1) as u16).unwrap_or(0),
                            (x + 1 < width && y > 0)
                                .then(|| get(x + 1, y - 1) as u16)
                                .unwrap_or(0),
                            (x > 0 && y + 1 < height)
                                .then(|| get(x - 1, y + 1) as u16)
                                .unwrap_or(0),
                            (x + 1 < width && y + 1 < height)
                                .then(|| get(x + 1, y + 1) as u16)
                                .unwrap_or(0),
                        ]
                        .iter()
                        .sum();
                        let rcnt = ((x > 0 && y > 0) as u16)
                            + ((x + 1 < width && y > 0) as u16)
                            + ((x > 0 && y + 1 < height) as u16)
                            + ((x + 1 < width && y + 1 < height) as u16);
                        let r = if rcnt > 0 { (rsum / rcnt) as u8 } else { 0 };
                        (r, g, bv)
                    }
                };

                out[0] = r;
                out[1] = g;
                out[2] = b;
            }
        }

        rgb
    }
}

#[cfg(test)]
mod tests;
