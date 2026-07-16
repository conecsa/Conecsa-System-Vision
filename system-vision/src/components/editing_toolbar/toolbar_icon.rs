//! Leptos UI components for the web frontend.

use leptos::prelude::*;

#[component]
pub(super) fn ToolbarIcon(children: Children) -> impl IntoView {
    view! {
        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            {children()}
        </svg>
    }
}
