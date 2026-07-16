//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn DetectionStoppedState() -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="flex flex-col items-center justify-center gap-4 w-full h-full text-center">
            <svg class="w-16 h-16 stroke-current ui-icon-muted opacity-50" viewBox="0 0 24 24" fill="none">
                <rect x="3" y="3" width="18" height="18" rx="2" stroke-width="2"/>
                <circle cx="8.5" cy="8.5" r="1.5" fill="currentColor"/>
                <polyline points="21 15 16 10 5 21" stroke-width="2"/>
            </svg>
            <p class="ui-value text-lg">{t!(i18n, stream::detection_stopped)}</p>
            <p class="ui-help text-sm">{t!(i18n, stream::start_detection_hint)}</p>
        </div>
    }
}
