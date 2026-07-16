//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::{training_image_url, DatasetSummary};
use crate::i18n::*;

/// Cover shown for datasets without any image (static asset in system-vision/public).
const DEFAULT_COVER: &str = "/public/dataset_default_cover.svg";

/// Cover url.
fn cover_url(ds: &DatasetSummary) -> String {
    if ds.cover_image_id.is_empty() {
        DEFAULT_COVER.to_string()
    } else {
        training_image_url(&ds.dataset_id, &ds.cover_image_id)
    }
}

/// One gallery card: cover, name, counts, hover export/rename/delete,
/// training badge.
#[component]
pub(super) fn DatasetCard(
    dataset: DatasetSummary,
    /// True while a training job runs on this dataset.
    training: Signal<bool>,
    on_open: Callback<DatasetSummary>,
    on_export: Callback<DatasetSummary>,
    on_rename: Callback<DatasetSummary>,
    on_delete: Callback<DatasetSummary>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (image_count, labeled_count, class_count) =
        (dataset.image_count, dataset.labeled_count, dataset.class_count);
    let ds_open = dataset.clone();
    let ds_export = dataset.clone();
    let ds_rename = dataset.clone();
    let ds_delete = dataset.clone();
    view! {
        <div
            class="ui-thumb ui-dataset-card"
            on:click=move |_| on_open.run(ds_open.clone())
        >
            <img
                src=cover_url(&dataset)
                class="ui-media-bg w-full aspect-square object-cover"
                alt=move || t_string!(i18n, training::dataset_cover_alt)
                loading="lazy"
            />
            <div class="ui-dataset-card-body">
                <span class="ui-dataset-card-name" title=dataset.name.clone()>
                    {dataset.name.clone()}
                </span>
                <span class="ui-dataset-card-meta">
                    {move || t_string!(
                        i18n,
                        training::dataset_card_meta,
                        images = image_count,
                        labeled = labeled_count,
                        classes = class_count
                    )}
                </span>
            </div>
            {move || if training.get() {
                view! {
                    <span class="ui-badge ui-badge-warning absolute top-1 left-1 px-1.5 py-0.5 text-[10px]">
                        {t_string!(i18n, training::training_badge)}
                    </span>
                }.into_any()
            } else {
                view! { <span/> }.into_any()
            }}
            <div class="ui-thumb-actions">
                <button
                    class="ui-thumb-action"
                    title=move || t_string!(i18n, training::export_dataset_title)
                    on:click=move |ev| {
                        ev.stop_propagation();
                        on_export.run(ds_export.clone());
                    }
                >
                    <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                </button>
                <button
                    class="ui-thumb-action"
                    title=move || t_string!(i18n, training::rename_dataset)
                    on:click=move |ev| {
                        ev.stop_propagation();
                        on_rename.run(ds_rename.clone());
                    }
                >
                    <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                </button>
                <button
                    class="ui-thumb-action ui-thumb-action-danger"
                    title=move || t_string!(i18n, training::delete_dataset)
                    on:click=move |ev| {
                        ev.stop_propagation();
                        on_delete.run(ds_delete.clone());
                    }
                >
                    <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                </button>
            </div>
        </div>
    }
}
