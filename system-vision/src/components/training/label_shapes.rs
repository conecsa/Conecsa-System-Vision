//! SVG overlay layers for the label canvas.
//!
//! These are plain view-builder functions (no component owners), so the
//! committed-boxes layer stays a single reactive closure that re-renders the
//! whole list on change — a per-box `<For>`/component would dispose+recreate
//! items mid-drag and panic on the disposed signal.

use leptos::prelude::*;

use crate::api::LabelBox;
use crate::i18n::*;

use super::label_geometry::{norm_coords, Corner, CORNERS, HANDLE, VIEW};
use crate::class_color::{class_color_for, class_display_name};

/// Committed boxes: each as a class-colored rect + label, plus white corner
/// resize handles on the selected one (outside SAM mode). Pointer events on a
/// rect/handle report up via the callbacks with the normalized click position;
/// in SAM mode the boxes are pointer-transparent so clicks become point prompts.
pub(super) fn committed_boxes_layer(
    i18n: leptos_i18n::I18nContext<Locale>,
    boxes: RwSignal<Vec<LabelBox>>,
    selected_box: RwSignal<Option<usize>>,
    sam_mode: ReadSignal<bool>,
    classes: ReadSignal<Vec<String>>,
    // on_box_down: (box index, normalized click) → select + start a move.
    on_box_down: Callback<(usize, (f32, f32))>,
    // on_handle_down: (box index, corner, normalized click) → start a resize.
    on_handle_down: Callback<(usize, Corner, (f32, f32))>,
) -> impl IntoView {
    move || {
        let sel = selected_box.get();
        let in_sam = sam_mode.get();
        let cls = classes.get();
        boxes.get().into_iter().enumerate().map(|(i, b)| {
            let color = class_color_for(b.class_id as usize, &cls);
            let label = cls.get(b.class_id as usize)
                .map(|e| class_display_name(e))
                .unwrap_or_else(|| t_string!(i18n, training::class_fallback, id = b.class_id));
            let x = (b.cx - b.w / 2.0) * VIEW;
            let y = (b.cy - b.h / 2.0) * VIEW;
            let right = (b.cx + b.w / 2.0) * VIEW;
            let bottom = (b.cy + b.h / 2.0) * VIEW;
            let is_sel = sel == Some(i);
            let handles = (is_sel && !in_sam).then(|| {
                let color = color.clone();
                [
                    (x, y, CORNERS[0]),
                    (right, y, CORNERS[1]),
                    (x, bottom, CORNERS[2]),
                    (right, bottom, CORNERS[3]),
                ].into_iter().map(move |(px, py, corner)| view! {
                    <rect
                        class=format!("ui-label-handle {}", corner.cursor_class())
                        x=px - HANDLE / 2.0
                        y=py - HANDLE / 2.0
                        width=HANDLE height=HANDLE
                        stroke=color.clone()
                        on:pointerdown=move |ev: leptos::ev::PointerEvent| {
                            ev.stop_propagation();
                            ev.prevent_default();
                            if let Some(o) = norm_coords(&ev) {
                                on_handle_down.run((i, corner, o));
                            }
                        }
                    />
                }).collect::<Vec<_>>()
            });
            view! {
                <rect
                    // SAM mode: locked = pointer-transparent so clicks become
                    // point prompts, not selection.
                    class=if in_sam { "ui-label-box-locked" } else { "ui-label-box" }
                    x=x y=y
                    width=b.w * VIEW height=b.h * VIEW
                    fill=if is_sel { format!("{}33", color) } else { "none".to_string() }
                    stroke=color.clone()
                    stroke-width=if is_sel { 4.0 } else { 2.5 }
                    on:pointerdown=move |ev: leptos::ev::PointerEvent| {
                        ev.stop_propagation();
                        ev.prevent_default();
                        if let Some(o) = norm_coords(&ev) {
                            on_box_down.run((i, o));
                        }
                    }
                />
                <text class="ui-label-text" x=x + 4.0 y=y + 16.0 fill=color>
                    {label}
                </text>
                {handles}
            }
        }).collect::<Vec<_>>()
    }
}

/// SAM suggestions — dashed boxes, not yet part of the labels.
pub(super) fn suggestions_layer(sam_suggestions: ReadSignal<Vec<LabelBox>>) -> impl IntoView {
    view! {
        <For
            each={move || sam_suggestions.get().into_iter().enumerate().collect::<Vec<_>>()}
            key=|(i, _)| *i
            children=move |(_, b): (usize, LabelBox)| view! {
                <rect
                    class="ui-label-suggestion"
                    x=(b.cx - b.w / 2.0) * VIEW
                    y=(b.cy - b.h / 2.0) * VIEW
                    width=b.w * VIEW
                    height=b.h * VIEW
                />
            }
        />
    }
}

/// SAM point prompts — green (positive) / red (negative) dots.
pub(super) fn points_layer(sam_points: RwSignal<Vec<(f32, f32, bool)>>) -> impl IntoView {
    view! {
        <For
            each={move || sam_points.get().into_iter().enumerate().collect::<Vec<_>>()}
            key=|(i, _)| *i
            children=move |(_, (x, y, positive)): (usize, (f32, f32, bool))| view! {
                <circle
                    class=if positive {
                        "ui-label-point ui-label-point-positive"
                    } else {
                        "ui-label-point ui-label-point-negative"
                    }
                    cx=x * VIEW cy=y * VIEW r="6"
                />
            }
        />
    }
}

/// The dashed rectangle drawn while dragging a new box on the background.
pub(super) fn draft_layer(
    draft: RwSignal<Option<(f32, f32, f32, f32)>>,
    classes: ReadSignal<Vec<String>>,
    active_class: ReadSignal<usize>,
) -> impl IntoView {
    move || draft.get().map(|(x0, y0, x1, y1)| view! {
        <rect
            class="ui-label-draft"
            x=x0.min(x1) * VIEW
            y=y0.min(y1) * VIEW
            width=(x1 - x0).abs() * VIEW
            height=(y1 - y0).abs() * VIEW
            stroke=class_color_for(active_class.get_untracked(), &classes.get_untracked())
        />
    })
}

/// Footer status: box count + the class new boxes will be drawn as. Labels
/// autosave, so there is no Save button — just this line.
pub(super) fn status_bar(
    i18n: leptos_i18n::I18nContext<Locale>,
    boxes: RwSignal<Vec<LabelBox>>,
    classes: ReadSignal<Vec<String>>,
    active_class: ReadSignal<usize>,
) -> impl IntoView {
    view! {
        <div class="flex items-center">
            <span class="ui-help">
                {move || t_string!(i18n, training::boxes_drawing_as, count = boxes.get().len())}
                <span class="font-semibold" style=move || classes.with(|c| format!(
                    "color: {}", class_color_for(active_class.get(), c)
                ))>
                    {move || classes.with(|c| c
                        .get(active_class.get())
                        .map(|e| class_display_name(e))
                        .unwrap_or_else(|| t_string!(i18n, training::no_class_yet).to_string()))}
                </span>
            </span>
        </div>
    }
}
