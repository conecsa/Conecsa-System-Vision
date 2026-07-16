//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn StreamInfoMessage(info_view: ReadSignal<Option<String>>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if let Some(stream_url) = info_view.get() {
            Some(view! {
                <div class="ui-alert ui-alert-info items-start py-2.5">
                    <svg class="w-4 h-4 mt-0.5 shrink-0 stroke-current" viewBox="0 0 24 24" fill="none">
                        <circle cx="12" cy="12" r="10" stroke-width="2"/>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 16v-4m0-4h.01" />
                    </svg>
                    <div class="flex-1 flex flex-col gap-1.5">
                        <div class="flex items-center gap-2">
                            <svg class="w-4 h-4 stroke-current fill-current" viewBox="0 0 24 24" fill="none">
                                <circle cx="12" cy="12" r="10" stroke-width="2"/>
                                <polygon points="10 8 16 12 10 16 10 8" fill="currentColor"/>
                            </svg>
                            <span class="font-semibold text-sm">{t_string!(i18n, main::stream_active)}</span>
                        </div>
                        <code class="ui-code-block">
                            {stream_url}
                        </code>
                    </div>
                </div>
            })
        } else {
            None
        }}
    }
}
