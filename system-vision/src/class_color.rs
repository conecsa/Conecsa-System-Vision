//! The `"name #hex"` class convention, shared by every renderer.
//!
//! A class entry is either `name` or `name #rgb` / `name #rrggbb`. The name is
//! everything before the trailing hex token; the hex is a display attribute.
//! An entry whose last token is not a valid hex (e.g. `item #3`) stays a plain
//! name.
//!
//! When a class carries no hex, the color falls back to a palette that is a
//! port of the inference service's `generate_colors` (`api/utils.py`) — same
//! base list, same HSV spread beyond it — so an uncolored class looks the same
//! in the label editor as it does on the burned-in live stream.

/// Base palette, mirroring `base_colors` in `inference-service/api/utils.py`
/// (that list is BGR; these are the same colors as RGB hex).
const BASE_COLORS: [&str; 10] = [
    "#ffa500", // orange
    "#ff0000", // red
    "#0000ff", // blue
    "#00ff00", // green
    "#00ffff", // cyan
    "#ff00ff", // magenta
    "#ffff00", // yellow
    "#800080", // purple
    "#00a5ff", // light orange
    "#808000", // teal
];

fn is_hex_color(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !(bytes.len() == 4 || bytes.len() == 7) || bytes[0] != b'#' {
        return false;
    }
    bytes[1..].iter().all(u8::is_ascii_hexdigit)
}

/// Split a raw class entry into its name and its optional `#hex` color.
pub fn parse_class_with_color(raw: &str) -> (String, Option<String>) {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return (String::new(), None);
    }

    if let Some((name, color)) = trimmed.rsplit_once(char::is_whitespace) {
        let color = color.trim();
        if is_hex_color(color) {
            return (name.trim().to_string(), Some(color.to_string()));
        }
    }

    (trimmed.to_string(), None)
}

/// The class name with any `#hex` suffix stripped — what the user should see.
pub fn class_display_name(entry: &str) -> String {
    let (name, _) = parse_class_with_color(entry);
    if name.is_empty() {
        entry.trim().to_string()
    } else {
        name
    }
}

/// The palette color for a class with no explicit hex.
///
/// Port of `generate_colors(num_classes)[index]`: the first ten come from
/// [`BASE_COLORS`], the rest are spread across the hue circle — which is why
/// `num_classes` matters, exactly as it does on the Python side.
fn generated_color(index: usize, num_classes: usize) -> String {
    if index < BASE_COLORS.len() || num_classes <= BASE_COLORS.len() {
        return BASE_COLORS[index % BASE_COLORS.len()].to_string();
    }

    let additional = (num_classes - BASE_COLORS.len()) as f32;
    let i = index - BASE_COLORS.len();
    let hue = (i as f32 / additional) % 1.0;
    let saturation = 0.8 + (i % 3) as f32 * 0.1;
    let value = 0.9 + (i % 2) as f32 * 0.1;

    let (r, g, b) = hsv_to_rgb(hue, saturation, value);
    format!("#{r:02x}{g:02x}{b:02x}")
}

/// `colorsys.hsv_to_rgb` + Python's truncating `int(x * 255)`.
fn hsv_to_rgb(h: f32, s: f32, v: f32) -> (u8, u8, u8) {
    let byte = |x: f32| (x * 255.0) as u8;
    if s == 0.0 {
        return (byte(v), byte(v), byte(v));
    }
    let sector = (h * 6.0) as i32;
    let f = h * 6.0 - sector as f32;
    let p = v * (1.0 - s);
    let q = v * (1.0 - f * s);
    let t = v * (1.0 - (1.0 - f) * s);
    let (r, g, b) = match sector % 6 {
        0 => (v, t, p),
        1 => (q, v, p),
        2 => (p, v, t),
        3 => (p, q, v),
        4 => (t, p, v),
        _ => (v, p, q),
    };
    (byte(r), byte(g), byte(b))
}

/// Expand `#rgb` to `#rrggbb`. Callers append an alpha pair to the result
/// (`{color}33`), which only yields valid CSS from a 6-digit base.
fn normalize_hex(color: &str) -> String {
    let digits = &color[1..];
    if digits.len() == 3 {
        let mut out = String::with_capacity(7);
        out.push('#');
        for c in digits.chars() {
            out.push(c);
            out.push(c);
        }
        return out;
    }
    color.to_string()
}

/// Resolve the box color for class `index` against the full class list: the
/// user's `#hex` when the entry carries one, otherwise the palette. Always
/// returns a `#rrggbb` string.
pub fn class_color_for(index: usize, classes: &[String]) -> String {
    if let Some((_, Some(color))) = classes.get(index).map(|e| parse_class_with_color(e)) {
        return normalize_hex(&color);
    }
    generated_color(index, classes.len())
}

#[cfg(test)]
mod tests;
