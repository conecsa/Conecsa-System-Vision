//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::DatasetSummary;
use crate::i18n::*;

/// Confirmation before permanently deleting a dataset. Visible while `target`
/// holds the dataset to delete; the gallery owns the state and the API call.
#[component]
pub(super) fn DatasetDeleteModal(
    target: ReadSignal<Option<DatasetSummary>>,
    busy: ReadSignal<bool>,
    on_confirm: Callback<()>,
    on_cancel: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if let Some(ds) = target.get() {
            view! {
                <div class="ui-modal-backdrop">
                    <div class="ui-card ui-card-pad ui-modal">
                        <h3 class="ui-card-title mb-2">{t_string!(i18n, training::delete_dataset_question)}</h3>
                        <p class="ui-help text-sm">
                            {if ds.image_count == 1 {
                                t_string!(i18n, training::delete_dataset_body_one, name = ds.name)
                            } else {
                                t_string!(
                                    i18n,
                                    training::delete_dataset_body,
                                    name = ds.name,
                                    count = ds.image_count
                                )
                            }}
                        </p>
                        <div class="ui-modal-actions">
                            <button
                                class="ui-button ui-button-neutral ui-button-md"
                                on:click=move |_| on_cancel.run(())
                            >
                                {t_string!(i18n, common::cancel)}
                            </button>
                            <button
                                class="ui-button ui-button-danger ui-button-md"
                                disabled=move || busy.get()
                                on:click=move |_| on_confirm.run(())
                            >
                                {move || if busy.get() {
                                    t_string!(i18n, training::deleting)
                                } else {
                                    t_string!(i18n, common::delete)
                                }}
                            </button>
                        </div>
                    </div>
                </div>
            }.into_any()
        } else {
            view! { <div/> }.into_any()
        }}
    }
}
