//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

/// Single "+" button in the top-right corner of the live stream. Emits a
/// `()` event on click; the parent owns the creation logic.
#[component]
pub fn AddAreaButton(on_add: Callback<()>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="absolute top-2 right-2">
            <button
                type="button"
                class="ui-overlay-toggle"
                title=move || t_string!(i18n, stream::add_detection_area)
                on:click=move |_| on_add.run(())
            >
                <svg class="w-5 h-5 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <rect x="5" y="5" width="10" height="10" rx="1.5" stroke-width="2" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 10v8m-4-4h8" />
                </svg>
            </button>
        </div>
    }
}
