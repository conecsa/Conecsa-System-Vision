//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

/// Lightweight projection of `api::DetectionArea` used by the
/// live-stream UI. Lives here because `AreaChips` is its primary consumer;
/// `LiveVideoStream` imports it from this module.
#[derive(Clone, Debug)]
pub struct AreaView {
    pub id: String,
    pub is_editing: bool,
    pub shape: String,
}

/// Chip strip in the top-left corner of the live stream. One chip per area:
/// clicking the label promotes that area into editing mode; clicking `✗`
/// deletes it.
#[component]
pub fn AreaChips(
    areas: ReadSignal<Vec<AreaView>>,
    on_edit: Callback<String>,
    on_delete: Callback<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="absolute top-2 left-2 flex flex-wrap gap-1 max-w-[60%]">
            {move || {
                areas.get().into_iter().enumerate().map(|(idx, a)| {
                    let id_edit = a.id.clone();
                    let id_del = a.id.clone();
                    let label = format!("#{}", idx + 1);
                    let shape_glyph = if a.shape == "circle" { "○" } else { "□" };
                    let highlight = if a.is_editing {
                        "ui-area-chip-active"
                    } else {
                        ""
                    };
                    let chip_class = format!("ui-area-chip {}", highlight);
                    view! {
                        <div class=chip_class>
                            <button
                                type="button"
                                class="hover:underline"
                                title=t_string!(i18n, stream::edit_area)
                                on:click=move |_| on_edit.run(id_edit.clone())
                            >
                                {shape_glyph} " " {label}
                            </button>
                            <button
                                type="button"
                                class="ui-area-chip-delete"
                                title=t_string!(i18n, stream::delete_area)
                                on:click=move |_| on_delete.run(id_del.clone())
                            >
                                "✗"
                            </button>
                        </div>
                    }
                }).collect_view()
            }}
        </div>
    }
}
