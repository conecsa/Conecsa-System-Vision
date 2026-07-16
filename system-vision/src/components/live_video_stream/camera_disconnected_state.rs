//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn CameraDisconnectedState() -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="flex flex-col items-center justify-center gap-4 w-full h-full text-center">
            <svg class="w-16 h-16 stroke-current ui-icon-muted opacity-50" viewBox="0 0 24 24" fill="none">
                <path d="M15 10.5V7a1 1 0 00-1-1H4a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1v-3.5z" stroke-width="2"/>
                <path d="M15 12l6-4v8l-6-4z" stroke-width="2" stroke-linejoin="round"/>
                <line x1="3" y1="21" x2="21" y2="3" stroke-width="2" stroke-linecap="round"/>
            </svg>
            <p class="ui-value text-lg">{t!(i18n, stream::camera_disconnected)}</p>
            <p class="ui-help text-sm">{t!(i18n, stream::camera_disconnected_hint)}</p>
        </div>
    }
}
