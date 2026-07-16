//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn CameraSettingsLoadingState() -> impl IntoView {
    let i18n = use_i18n();

    view! {
        <div class="ui-muted flex items-center justify-center py-10">
            <svg class="animate-spin w-5 h-5 mr-2" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            {t!(i18n, common::loading)}
        </div>
    }
}
