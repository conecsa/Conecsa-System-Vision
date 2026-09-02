//! Leptos UI components for the web frontend.

use leptos::prelude::*;
use wasm_bindgen::JsCast;

use crate::api::{training_image_url, LabelBox};
use crate::i18n::*;

use super::label_geometry::{
    apply_drag, is_background, norm_coords, BoxDrag, Corner, DragKind, DRAG_EPS, VIEW,
};
use super::label_shapes::{
    committed_boxes_layer, draft_layer, points_layer, status_bar, suggestions_layer,
};

/// The drawing surface: the dataset image with an SVG overlay for the boxes,
/// resize handles, SAM suggestions/points and the in-progress draft rectangle.
///
/// Owns the `draft` rectangle and all pointer handling; the rendering of each
/// overlay layer lives in `label_shapes`. Selection (`selected_box`) and the
/// active move/resize (`drag`) are owned by the parent so the toolbar and the
/// global Delete/pointerup listeners can share them. Uses Pointer Events so
/// mouse, touch and pen all draw.
#[component]
pub(super) fn LabelCanvas(
    dataset_id: String,
    selected: ReadSignal<Option<String>>,
    boxes: RwSignal<Vec<LabelBox>>,
    classes: ReadSignal<Vec<String>>,
    active_class: ReadSignal<usize>,
    selected_box: RwSignal<Option<usize>>,
    drag: RwSignal<Option<BoxDrag>>,
    sam_mode: ReadSignal<bool>,
    sam_points: RwSignal<Vec<(f32, f32, bool)>>,
    sam_suggestions: ReadSignal<Vec<LabelBox>>,
    /// Persist the current boxes (true = show a toast).
    on_save: Callback<bool>,
    /// Fired when the user tries to draw a box with no class selected.
    on_need_class: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Copy-able handle so the canvas closure can build per-image URLs.
    let dataset_id = StoredValue::new(dataset_id);
    // Draft rectangle while drawing a new box, normalized (x0, y0, x1, y1).
    let draft = RwSignal::new(None::<(f32, f32, f32, f32)>);

    // The canvas is width-driven in a fixed, non-scrolling viewport. Cap its
    // width by the available height so it always fits vertically; when the SAM
    // panel is open it eats ~11rem more, so shrink the canvas to match (16rem ≈
    // top bar + toolbar + status; +11rem for the SAM controls). The image
    // branch scales this cap by the image's aspect ratio (see `canvas_box`).
    let canvas_height_avail = move || {
        if sam_mode.get() {
            "100dvh - 27rem"
        } else {
            "100dvh - 16rem"
        }
    };
    let canvas_cap = move || {
        if sam_mode.get() {
            "max-w-[calc(100dvh-27rem)]"
        } else {
            "max-w-[calc(100dvh-16rem)]"
        }
    };

    // ── interaction ─────────────────────────────────────────────────────────

    let arm_drag = move |idx: usize, kind: DragKind, origin: (f32, f32)| {
        if let Some(bx) = boxes.get_untracked().get(idx) {
            drag.set(Some(BoxDrag {
                idx,
                kind,
                origin,
                start: (bx.cx, bx.cy, bx.w, bx.h),
                moved: false,
            }));
        }
    };

    // Reported by a box/handle rect when pressed (with the normalized click).
    let on_box_down = Callback::new(move |(idx, origin): (usize, (f32, f32))| {
        selected_box.set(Some(idx));
        arm_drag(idx, DragKind::Move, origin);
    });
    let on_handle_down = Callback::new(move |(idx, corner, origin): (usize, Corner, (f32, f32))| {
        arm_drag(idx, DragKind::Resize(corner), origin);
    });

    // SVG-level handler: only true background presses (on the svg itself).
    // Presses on a box/handle are handled by that element's own on:pointerdown.
    // In SAM mode the box rects are pointer-transparent, so every press reaches
    // here and becomes a point prompt. Pointer (not mouse) events so touch and
    // pen work too — `PointerEvent` derefs to `MouseEvent`, so the geometry
    // helpers and shift/ctrl modifiers are unchanged.
    let on_pointer_down = move |ev: leptos::ev::PointerEvent| {
        if selected.get_untracked().is_none() || !is_background(&ev) {
            return;
        }
        let Some((x, y)) = norm_coords(&ev) else {
            return;
        };
        ev.prevent_default();
        if sam_mode.get_untracked() {
            let positive = !(ev.shift_key() || ev.ctrl_key());
            sam_points.update(|p| p.push((x, y, positive)));
        } else {
            // Background: clear selection and start drawing a new box.
            selected_box.set(None);
            draft.set(Some((x, y, x, y)));
        }
    };

    let on_pointer_move = move |ev: leptos::ev::PointerEvent| {
        let active_drag = drag.get_untracked();
        if active_drag.is_none() && draft.get_untracked().is_none() {
            return;
        }
        let Some((x, y)) = norm_coords(&ev) else {
            return;
        };
        if let Some(mut d) = active_drag {
            let (cx, cy, w, h) = apply_drag(&d, x, y);
            let idx = d.idx;
            boxes.update(|bs| {
                if let Some(b) = bs.get_mut(idx) {
                    b.cx = cx;
                    b.cy = cy;
                    b.w = w;
                    b.h = h;
                }
            });
            if !d.moved
                && ((x - d.origin.0).abs() > DRAG_EPS || (y - d.origin.1).abs() > DRAG_EPS)
            {
                d.moved = true;
                drag.set(Some(d));
            }
            return;
        }
        draft.update(|d| {
            if let Some(d) = d.as_mut() {
                d.2 = x;
                d.3 = y;
            }
        });
    };

    let commit_draft = move |_: leptos::ev::PointerEvent| {
        // Finishing a move/resize: persist only if the box actually changed
        // (a plain click on a box just selects it).
        if let Some(d) = drag.get_untracked() {
            drag.set(None);
            if d.moved {
                on_save.run(false);
            }
            return;
        }
        let Some((x0, y0, x1, y1)) = draft.get_untracked() else {
            return;
        };
        draft.set(None);
        let (w, h) = ((x1 - x0).abs(), (y1 - y0).abs());
        // Ignore accidental clicks (boxes smaller than ~1% of the image).
        if w < 0.01 || h < 0.01 {
            return;
        }
        // A box needs a real class id, or set_labels rejects the save with
        // "Unknown class id". Block drawing until a class exists.
        if active_class.get_untracked() >= classes.get_untracked().len() {
            on_need_class.run(());
            return;
        }
        boxes.update(|bs| {
            bs.push(LabelBox {
                class_id: active_class.get_untracked() as u32,
                cx: (x0 + x1) / 2.0,
                cy: (y0 + y1) / 2.0,
                w,
                h,
            });
        });
        on_save.run(false);
    };

    // ── view ────────────────────────────────────────────────────────────────

    view! {
        {move || match selected.get() {
            // No image yet: a square placeholder, width-driven (aspect-square)
            // and capped by the viewport height so it always fits vertically in
            // the fixed, non-scrolling app shell.
            None => view! {
                <div class=move || format!(
                    "ui-list-box aspect-square w-full {} mx-auto flex items-center justify-center text-sm ui-muted",
                    canvas_cap()
                )>
                    {t_string!(i18n, training::select_image_hint)}
                </div>
            }.into_any(),
            // Dataset images are not necessarily square (native-resolution
            // datasets store the 16:9 stereo-combined frame), and the image is
            // an `<img src=…>` — its size is only known once the browser has
            // decoded it. Read natural_width/height on `load` and size the
            // container by that ratio (square until then, so the layout does
            // not jump to zero height); the `<img>` and `<svg>` both fill the
            // container, so the picture is never distorted. The signal lives in
            // this branch so switching images starts from the fallback again.
            Some(image_id) => {
                let img_size = RwSignal::new(None::<(u32, u32)>);
                let on_img_load = move |ev: leptos::ev::Event| {
                    let Some(img) = ev
                        .target()
                        .and_then(|t| t.dyn_into::<web_sys::HtmlImageElement>().ok())
                    else {
                        return;
                    };
                    let (w, h) = (img.natural_width(), img.natural_height());
                    if w > 0 && h > 0 {
                        img_size.set(Some((w, h)));
                    }
                };
                let aspect = move || {
                    img_size
                        .get()
                        .map(|(w, h)| format!("{w} / {h}"))
                        .unwrap_or_else(|| "1 / 1".to_string())
                };
                // Height-fit cap scaled by the aspect ratio: a 16:9 image may be
                // wider than the square cap and still fit the available height.
                let canvas_box = move || {
                    let (w, h) = img_size.get().unwrap_or((1, 1));
                    format!("calc(({}) * {w} / {h})", canvas_height_avail())
                };
                view! {
                    <div
                        class="ui-media-bg relative w-full mx-auto rounded overflow-hidden select-none"
                        style=("aspect-ratio", aspect)
                        style=("max-width", canvas_box)
                    >
                        <img
                            src=training_image_url(&dataset_id.get_value(), &image_id)
                            class="absolute inset-0 w-full h-full pointer-events-none"
                            alt=t_string!(i18n, training::labeling_image_alt)
                            draggable="false"
                            on:load=on_img_load
                        />
                        // touch-none: claim the gesture so a finger-drag draws a box
                        // instead of scrolling/zooming the page (browsers cancel
                        // pointermove mid-pan otherwise).
                        //
                        // preserveAspectRatio="none": the 640-unit viewBox stretches
                        // to the same box as the image, so normalized cx/cy/w/h keep
                        // mapping 1:1 onto the picture with no per-axis scale in the
                        // drawing or pointer math (`norm_coords` measures x and y
                        // against the svg's own width and height). Side effect: on a
                        // 16:9 image the square resize handles render slightly wider
                        // than tall — acceptable.
                        <svg
                            class="absolute inset-0 w-full h-full cursor-crosshair touch-none"
                            viewBox=format!("0 0 {} {}", VIEW, VIEW)
                            preserveAspectRatio="none"
                            on:pointerdown=on_pointer_down
                            on:pointermove=on_pointer_move
                            on:pointerup=commit_draft
                            on:pointerleave=move |_| draft.set(None)
                        >
                            {committed_boxes_layer(i18n, boxes, selected_box, sam_mode, classes, on_box_down, on_handle_down)}
                            {suggestions_layer(sam_suggestions)}
                            {points_layer(sam_points)}
                            {draft_layer(draft, classes, active_class)}
                        </svg>
                    </div>
                    {status_bar(i18n, boxes, classes, active_class)}
                }.into_any()
            }
        }}
    }
}
