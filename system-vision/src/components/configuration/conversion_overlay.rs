//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ConversionOverlay(
    active_job_id: ReadSignal<Option<String>>,
    message: ReadSignal<String>,
    progress: ReadSignal<u8>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if active_job_id.get().is_some() {
            let progress_value = progress.get();
            let msg = message.get();
            view! {
                <div class="ui-overlay-panel absolute inset-0 z-40 flex flex-col items-center justify-center">
                    <svg class="animate-spin w-10 h-10 ui-accent mb-4" viewBox="0 0 24 24" fill="none">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    <p class="ui-value text-sm mb-3 text-center max-w-xs px-2">{msg}</p>
                    {if progress_value > 0 {
                        view! {
                            <div class="w-48">
                                <div class="ui-help flex justify-between mb-1">
                                    <span>{t!(i18n, models::progress)}</span>
                                    <span>{format!("{}%", progress_value)}</span>
                                </div>
                                <div class="ui-progress-track">
                                    <div
                                        class="ui-progress-bar ui-progress-bar-primary"
                                        style={format!("width: {}%", progress_value)}
                                    />
                                </div>
                            </div>
                        }.into_any()
                    } else {
                        view! { <div/> }.into_any()
                    }}
                    <p class="ui-help mt-3 italic">{t!(i18n, models::do_not_close_tab)}</p>
                </div>
            }.into_any()
        } else {
            view! { <div/> }.into_any()
        }}
    }
}
