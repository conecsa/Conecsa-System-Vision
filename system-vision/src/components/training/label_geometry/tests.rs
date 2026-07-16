//! Unit tests for the pure label-editor geometry (headless browser).
use super::*;
use wasm_bindgen_test::*;

fn approx(a: f32, b: f32) {
    assert!((a - b).abs() < 1e-5, "{a} != {b}");
}

#[wasm_bindgen_test]
fn corner_cursor_classes() {
    assert_eq!(Corner::Nw.cursor_class(), "ui-label-handle-nwse");
    assert_eq!(Corner::Se.cursor_class(), "ui-label-handle-nwse");
    assert_eq!(Corner::Ne.cursor_class(), "ui-label-handle-nesw");
    assert_eq!(Corner::Sw.cursor_class(), "ui-label-handle-nesw");
}

#[wasm_bindgen_test]
fn edges_round_trips_through_from_edges() {
    let (cx, cy, w, h) = (0.5, 0.5, 0.2, 0.4);
    let (l, t, r, b) = edges(cx, cy, w, h);
    approx(l, 0.4);
    approx(t, 0.3);
    approx(r, 0.6);
    approx(b, 0.7);
    let (cx2, cy2, w2, h2) = from_edges(l, t, r, b);
    approx(cx2, cx);
    approx(cy2, cy);
    approx(w2, w);
    approx(h2, h);
}

#[wasm_bindgen_test]
fn from_edges_is_order_agnostic() {
    // Passing corners swapped still yields a positive-size box.
    let (cx, cy, w, h) = from_edges(0.6, 0.7, 0.4, 0.3);
    approx(cx, 0.5);
    approx(cy, 0.5);
    approx(w, 0.2);
    approx(h, 0.4);
}

fn move_drag(origin: (f32, f32), start: (f32, f32, f32, f32)) -> BoxDrag {
    BoxDrag {
        idx: 0,
        kind: DragKind::Move,
        origin,
        start,
        moved: false,
    }
}

#[wasm_bindgen_test]
fn apply_drag_move_keeps_size_and_translates() {
    let d = move_drag((0.5, 0.5), (0.5, 0.5, 0.2, 0.2));
    let (cx, cy, w, h) = apply_drag(&d, 0.6, 0.55);
    approx(w, 0.2);
    approx(h, 0.2);
    approx(cx, 0.6);
    approx(cy, 0.55);
}

#[wasm_bindgen_test]
fn apply_drag_move_clamps_inside_canvas() {
    let d = move_drag((0.5, 0.5), (0.9, 0.9, 0.2, 0.2));
    // Drag far past the bottom-right edge; box stays fully inside [0,1].
    let (cx, cy, w, h) = apply_drag(&d, 2.0, 2.0);
    let (l, t, r, b) = edges(cx, cy, w, h);
    assert!(l >= -1e-6 && t >= -1e-6);
    assert!(r <= 1.0 + 1e-6 && b <= 1.0 + 1e-6);
    approx(w, 0.2);
    approx(h, 0.2);
}

#[wasm_bindgen_test]
fn apply_drag_resize_se_enforces_min_size() {
    let d = BoxDrag {
        idx: 0,
        kind: DragKind::Resize(Corner::Se),
        origin: (0.5, 0.5),
        start: (0.5, 0.5, 0.4, 0.4), // edges l=0.3, t=0.3, r=0.7, b=0.7
        moved: false,
    };
    // Drag the SE corner back onto the NW corner -> clamped to MIN_SIZE.
    let (_cx, _cy, w, h) = apply_drag(&d, 0.0, 0.0);
    assert!(w >= MIN_SIZE - 1e-6);
    assert!(h >= MIN_SIZE - 1e-6);
    approx(w, MIN_SIZE);
    approx(h, MIN_SIZE);
}
