//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::{LabelBox, SamStatusResponse};
use crate::class_color::class_display_name;
use crate::i18n::*;

/// Header row of the label editor: the card title, the selected-box controls
/// (reassign its class, delete it) and the AI-assist (SAM) toggle.
#[component]
pub(super) fn LabelToolbar(
    selected_box: ReadSignal<Option<usize>>,
    boxes: ReadSignal<Vec<LabelBox>>,
    classes: ReadSignal<Vec<String>>,
    /// Reassign the selected box's class.
    on_set_class: Callback<u32>,
    /// Delete the selected box.
    on_delete: Callback<()>,
    sam_status: ReadSignal<Option<SamStatusResponse>>,
    sam_busy: ReadSignal<bool>,
    sam_mode: ReadSignal<bool>,
    on_sam_toggle: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    let sam_available = move || sam_status.get().map(|s| s.available).unwrap_or(false);
    let sam_unavailable_msg = move || {
        sam_status
            .get()
            .map(|s| s.message)
            .filter(|m| !m.is_empty())
            .unwrap_or_else(|| t_string!(i18n, training::ai_unavailable).to_string())
    };

    view! {
        <div class="flex items-center justify-between gap-2 flex-wrap">
            <h2 class="ui-card-title">{t!(i18n, training::label_editor_title)}</h2>
            <div class="flex items-center gap-2 flex-wrap">
                {move || match selected_box.get() {
                    Some(idx) => {
                        let current = boxes.get().get(idx).map(|b| b.class_id).unwrap_or(0);
                        let class_list = classes.get();
                        view! {
                            <select
                                class="ui-select ui-select-sm w-auto cursor-pointer"
                                title=t_string!(i18n, training::reassign_box_class)
                                on:change=move |ev| {
                                    if let Ok(v) = event_target_value(&ev).parse::<u32>() {
                                        on_set_class.run(v);
                                    }
                                }
                            >
                                {class_list.iter().enumerate().map(|(ci, name)| {
                                    let selected = ci as u32 == current;
                                    view! {
                                        <option value={ci.to_string()} selected={selected}>
                                            {class_display_name(name)}
                                        </option>
                                    }
                                }).collect::<Vec<_>>()}
                            </select>
                            <button
                                class="ui-button ui-button-danger ui-button-xs"
                                on:click=move |_| on_delete.run(())
                                title=t_string!(i18n, training::delete_box_title)
                            >
                                {t_string!(i18n, training::delete_box)}
                            </button>
                        }.into_any()
                    }
                    None => view! { <span/> }.into_any(),
                }}
                <button
                    class=move || format!(
                        "ui-button ui-button-xs {}",
                        if sam_mode.get() {
                            "ui-button-primary"
                        } else {
                            "ui-button-neutral"
                        }
                    )
                    disabled=move || !sam_available() || sam_busy.get()
                    title=move || if sam_available() {
                        t_string!(i18n, training::toggle_ai_title).to_string()
                    } else {
                        sam_unavailable_msg()
                    }
                    on:click=move |_| on_sam_toggle.run(())
                >
                    {move || if sam_busy.get() {
                        t_string!(i18n, training::ai_loading)
                    } else if sam_mode.get() {
                        t_string!(i18n, training::ai_on)
                    } else {
                        t_string!(i18n, training::ai_off)
                    }}
                </button>
            </div>
        </div>
    }
}
