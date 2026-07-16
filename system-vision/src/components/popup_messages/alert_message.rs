//! Leptos UI components for the web frontend.

use leptos::prelude::*;

#[derive(Clone, Copy)]
pub(super) enum AlertKind {
    Error,
    Success,
}

#[component]
pub(super) fn AlertMessage(message: ReadSignal<String>, kind: AlertKind) -> impl IntoView {
    view! {
        {move || if !message.get().is_empty() {
            let class = match kind {
                AlertKind::Error => "ui-alert ui-alert-error",
                AlertKind::Success => "ui-alert ui-alert-success",
            };
            Some(view! {
                <div class=class>
                    {match kind {
                        AlertKind::Error => view! {
                            <svg class="w-4 h-4 shrink-0 stroke-current" viewBox="0 0 24 24" fill="none">
                                <circle cx="12" cy="12" r="10" stroke-width="2"/>
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01" />
                            </svg>
                        }.into_any(),
                        AlertKind::Success => view! {
                            <svg class="w-4 h-4 shrink-0 stroke-current" viewBox="0 0 24 24" fill="none">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        }.into_any(),
                    }}
                    <span class="font-medium">{message.get()}</span>
                </div>
            })
        } else {
            None
        }}
    }
}
