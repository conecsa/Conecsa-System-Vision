//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn LoadingStreamState() -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="flex flex-col items-center justify-center gap-4 w-full h-full">
            <svg class="w-16 h-16 stroke-current ui-icon-muted opacity-50" viewBox="0 0 24 24" fill="none">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p class="ui-value text-lg">{t!(i18n, common::loading)}</p>
        </div>
    }
}
