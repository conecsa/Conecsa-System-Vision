//! Pure geometry + interaction primitives shared by the label-editor pieces.
//!
//! No Leptos/DOM state here beyond reading a `MouseEvent` — just the math for
//! YOLO boxes (normalized cx/cy/w/h on the square 640×640 canvas) and the
//! move/resize drag model.

use wasm_bindgen::JsCast;

/// Side of the square SVG viewBox (also the dataset image size).
pub(super) const VIEW: f32 = 640.0;
/// Minimum normalized box side; smaller draws/resizes are rejected/clamped.
pub(super) const MIN_SIZE: f32 = 0.01;
/// Resize-handle side in viewBox units (~1.4% of the 640 canvas) — kept small
/// so it doesn't cover up smaller labels while editing.
pub(super) const HANDLE: f32 = 9.0;
/// Pointer travel (normalized) past which a box mousedown counts as a drag
/// rather than a plain select — below it, no save fires.
pub(super) const DRAG_EPS: f32 = 0.003;

/// The four corners, in handle render order.
pub(super) const CORNERS: [Corner; 4] = [Corner::Nw, Corner::Ne, Corner::Sw, Corner::Se];

#[derive(Clone, Copy, PartialEq)]
pub(super) enum Corner {
    Nw,
    Ne,
    Sw,
    Se,
}

impl Corner {
    /// CSS modifier class carrying the right resize cursor.
    pub(super) fn cursor_class(self) -> &'static str {
        match self {
            Corner::Nw | Corner::Se => "ui-label-handle-nwse",
            Corner::Ne | Corner::Sw => "ui-label-handle-nesw",
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum DragKind {
    Move,
    Resize(Corner),
}

/// An in-progress move/resize of an existing committed box.
#[derive(Clone, Copy)]
pub(super) struct BoxDrag {
    pub(super) idx: usize,
    pub(super) kind: DragKind,
    pub(super) origin: (f32, f32),          // pointer (normalized) at mousedown
    pub(super) start: (f32, f32, f32, f32), // box (cx, cy, w, h) at mousedown
    pub(super) moved: bool,                 // crossed DRAG_EPS → a real edit, will save
}

/// Mouse position normalized to 0..1 within the SVG canvas. Resolves the
/// enclosing `<svg>` from `event.target` (the real element under the cursor —
/// a child `<rect>`, handle, or the svg itself), so the scale is measured
/// against the full square canvas. NB: `current_target` is unusable here —
/// Leptos delegates events on `window`, so it is the window, not the svg.
pub(super) fn norm_coords(ev: &leptos::ev::MouseEvent) -> Option<(f32, f32)> {
    let target: web_sys::Element = ev.target()?.dyn_into().ok()?;
    let svg = target.closest("svg").ok().flatten()?;
    let rect = svg.get_bounding_client_rect();
    if rect.width() <= 0.0 || rect.height() <= 0.0 {
        return None;
    }
    let x = ((ev.client_x() as f64 - rect.left()) / rect.width()).clamp(0.0, 1.0);
    let y = ((ev.client_y() as f64 - rect.top()) / rect.height()).clamp(0.0, 1.0);
    Some((x as f32, y as f32))
}

/// True when the click landed on the `<svg>` canvas itself (empty background),
/// not on a child `<rect>`. Box/handle rects carry their own on:mousedown that
/// captures their index in Rust — DOM `data-*` attributes are unreliable here
/// (Leptos mangles `attr:data-foo` to a literal `attr:data-foo` name on SVG).
pub(super) fn is_background(ev: &leptos::ev::MouseEvent) -> bool {
    ev.target()
        .and_then(|t| t.dyn_into::<web_sys::Element>().ok())
        .map(|e| e.tag_name().eq_ignore_ascii_case("svg"))
        .unwrap_or(false)
}

/// (left, top, right, bottom) of a YOLO box.
fn edges(cx: f32, cy: f32, w: f32, h: f32) -> (f32, f32, f32, f32) {
    (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
}

/// YOLO (cx, cy, w, h) from edges (order-agnostic).
fn from_edges(l: f32, t: f32, r: f32, b: f32) -> (f32, f32, f32, f32) {
    let (l, r) = (l.min(r), l.max(r));
    let (t, b) = (t.min(b), t.max(b));
    ((l + r) / 2.0, (t + b) / 2.0, r - l, b - t)
}

/// New box geometry for a drag at pointer `(mx, my)`. Move keeps the size and
/// clamps the box inside `[0,1]`; Resize anchors the opposite corner and enforces
/// a minimum side.
pub(super) fn apply_drag(d: &BoxDrag, mx: f32, my: f32) -> (f32, f32, f32, f32) {
    let (cx, cy, w, h) = d.start;
    let (l, t, r, b) = edges(cx, cy, w, h);
    match d.kind {
        DragKind::Move => {
            let nl = (l + (mx - d.origin.0)).clamp(0.0, 1.0 - w);
            let nt = (t + (my - d.origin.1)).clamp(0.0, 1.0 - h);
            (nl + w / 2.0, nt + h / 2.0, w, h)
        }
        DragKind::Resize(corner) => {
            let mx = mx.clamp(0.0, 1.0);
            let my = my.clamp(0.0, 1.0);
            let (nl, nt, nr, nb) = match corner {
                Corner::Nw => (mx.min(r - MIN_SIZE), my.min(b - MIN_SIZE), r, b),
                Corner::Ne => (l, my.min(b - MIN_SIZE), mx.max(l + MIN_SIZE), b),
                Corner::Sw => (mx.min(r - MIN_SIZE), t, r, my.max(t + MIN_SIZE)),
                Corner::Se => (l, t, mx.max(l + MIN_SIZE), my.max(t + MIN_SIZE)),
            };
            from_edges(nl, nt, nr, nb)
        }
    }
}

#[cfg(test)]
mod tests;
