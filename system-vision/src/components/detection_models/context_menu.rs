//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ModelContextMenu(
    visible: ReadSignal<bool>,
    x: ReadSignal<i32>,
    y: ReadSignal<i32>,
    on_confirm_delete: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Hardening: the menu never opens for common users (model_row guards the
    // contextmenu), but keep the delete action itself gated too.
    let privileged = crate::components::access::privileged();
    view! {
        {move || if visible.get() {
            view! {
                <div
                    class="ui-menu fixed z-50 min-w-40"
                    style:left=move || format!("{}px", x.get())
                    style:top=move || format!("{}px", y.get() - 100)
                >
                    <button
                        class="ui-menu-item ui-menu-item-danger disabled:opacity-50 disabled:cursor-not-allowed"
                        disabled=!privileged
                        on:click=move |_| on_confirm_delete.run(())
                    >
                        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        {t!(i18n, models::delete_model)}
                    </button>
                </div>
            }.into_any()
        } else {
            view! { <div style="display: none;"></div> }.into_any()
        }}
    }
}
