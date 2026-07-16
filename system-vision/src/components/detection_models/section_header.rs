//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ModelSectionHeader(
    active_model: Signal<Option<String>>,
    on_download: Callback<()>,
    on_upload: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Role gating: model download/upload are admin-only; selection stays open.
    let privileged = crate::components::access::privileged();
    let restricted_title = move || {
        if privileged {
            ""
        } else {
            t_string!(i18n, common::restricted_to_admins)
        }
    };
    view! {
        <div class="flex justify-between items-center mb-2">
            <h3 class="ui-section-title">{t!(i18n, models::detection_models_title)}</h3>
            <div class="flex items-center gap-2">
                <Show when=move || active_model.get().is_some()>
                    <button
                        class="ui-button ui-button-neutral ui-button-sm disabled:opacity-50 disabled:cursor-not-allowed"
                        disabled=!privileged
                        title=restricted_title
                        on:click=move |_| on_download.run(())
                    >
                        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M12 4v12m0 0l-4-4m4 4l4-4" />
                        </svg>
                        {t!(i18n, models::download)}
                    </button>
                </Show>
                <button
                    class="ui-button ui-button-primary ui-button-sm disabled:opacity-50 disabled:cursor-not-allowed"
                    disabled=!privileged
                    title=restricted_title
                    on:click=move |_| on_upload.run(())
                >
                    <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                    {t!(i18n, models::upload_model)}
                </button>
            </div>
        </div>
    }
}
