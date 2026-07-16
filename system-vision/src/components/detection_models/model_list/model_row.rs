//! Leptos UI components for the web frontend.

use crate::app::{format_size, ModelInfo};
use crate::i18n::*;
use leptos::prelude::*;

use wasm_bindgen::JsCast;

#[component]
pub(super) fn ModelRow(
    model: ModelInfo,
    on_select: Callback<String>,
    set_context_menu_x: WriteSignal<i32>,
    set_context_menu_y: WriteSignal<i32>,
    set_selected_model_for_delete: WriteSignal<String>,
    set_context_menu_visible: WriteSignal<bool>,
    set_error_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Role gating: deleting models (context menu) is admin-only.
    let privileged = crate::components::access::privileged();
    let model_name_for_context = model.name.clone();
    let model_name_for_select = model.name.clone();
    let is_active = model.is_active;

    view! {
        <div
            class={if model.is_active {
                "ui-row ui-row-clickable ui-row-selected px-4 py-3.5"
            } else {
                "ui-row ui-row-clickable px-4 py-3.5"
            }}
            on:contextmenu=move |ev| {
                ev.prevent_default();
                if !privileged {
                    return;
                }
                if !is_active {
                    if let Some(mouse_event) = ev.dyn_ref::<web_sys::MouseEvent>() {
                        set_context_menu_x.set(mouse_event.client_x());
                        set_context_menu_y.set(mouse_event.client_y());
                        set_selected_model_for_delete.set(model_name_for_context.clone());
                        set_context_menu_visible.set(true);
                    }
                } else {
                    let locale = i18n.get_locale_untracked();
                    set_error_msg.set(
                        td_string!(locale, models::cannot_delete_active_model).to_string(),
                    );
                }
            }
        >
            <div class="flex flex-col gap-1">
                <span class="ui-value text-sm">{model.name.clone()}</span>
                <span class="ui-help">{format_size(model.size)}</span>
            </div>
            {if model.is_active {
                view! {
                    <span class="ui-badge ui-badge-primary">
                        {t!(i18n, models::active)}
                    </span>
                }.into_any()
            } else {
                view! {
                    <button
                        class="ui-button ui-button-primary ui-button-xs"
                        on:click=move |_| {
                            on_select.run(model_name_for_select.clone());
                        }
                    >
                        {t!(i18n, models::select)}
                    </button>
                }.into_any()
            }}
        </div>
    }
}
