//! Leptos UI components for the web frontend.

use super::PANEL_ID;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ImageAdjustmentToggleButton(panel: RwSignal<u8>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="absolute top-2 right-14">
            <button
                type="button"
                class=move || {
                    if panel.get() == PANEL_ID {
                        "ui-overlay-toggle ui-overlay-toggle-active"
                    } else {
                        "ui-overlay-toggle"
                    }
                }
                title=move || t_string!(i18n, stream::image_adjust_tooltip)
                on:click=move |_| panel.update(|p| *p = if *p == PANEL_ID { 0 } else { PANEL_ID })
            >
                <svg class="w-5 h-5 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h10M18 6h2M14 6a2 2 0 104 0 2 2 0 00-4 0zM4 12h2M10 12h10M6 12a2 2 0 104 0 2 2 0 00-4 0zM4 18h10M18 18h2M14 18a2 2 0 104 0 2 2 0 00-4 0z" />
                </svg>
            </button>
        </div>
    }
}
