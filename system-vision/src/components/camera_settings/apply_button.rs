//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ApplyCameraSettingsButton(
    saving: ReadSignal<bool>,
    on_apply: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();

    view! {
        <div class="ui-section-rule-sm">
            <button
                class={move || {
                    if saving.get() {
                        "ui-button ui-button-primary ui-button-md w-full"
                    } else {
                        "ui-button ui-button-primary ui-button-md w-full"
                    }
                }}
                on:click=move |_| on_apply.run(())
                disabled=move || saving.get()
            >
                {move || if saving.get() {
                    view! {
                        <>
                            <svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                            </svg>
                            {t_string!(i18n, camera::applying)}
                        </>
                    }.into_any()
                } else {
                    view! {
                        <>
                            <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                    d="M5 13l4 4L19 7"/>
                            </svg>
                            {t_string!(i18n, camera::apply_settings)}
                        </>
                    }.into_any()
                }}
            </button>
        </div>
    }
}
