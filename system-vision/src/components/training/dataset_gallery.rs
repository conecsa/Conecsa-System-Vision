//! Leptos UI components for the web frontend.

use leptos::prelude::*;
use leptos::task::spawn_local;
use wasm_bindgen::JsCast;

use crate::api;
use crate::api::DatasetSummary;
use crate::i18n::*;

use super::dataset_card::DatasetCard;
use super::dataset_delete_modal::DatasetDeleteModal;
use super::dataset_name_modal::DatasetNameModal;
use super::dataset_upload_modal::DatasetUploadModal;

/// Job is active.
fn job_is_active(status: &str) -> bool {
    matches!(status, "preparing" | "training" | "uploading")
}

/// Dataset gallery: cards for every dataset (cover, name, counts) plus
/// create/upload entry points. Selecting a card opens the dataset editor.
#[component]
pub(super) fn DatasetGallery(
    on_open: Callback<DatasetSummary>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (datasets, set_datasets) = signal(Vec::<DatasetSummary>::new());
    let (loading, set_loading) = signal(true);
    // dataset_id of a currently running training job (badge on its card).
    let (training_ds, set_training_ds) = signal(String::new());

    let (show_create, set_show_create) = signal(false);
    let (show_upload, set_show_upload) = signal(false);
    let (rename_target, set_rename_target) = signal(None::<DatasetSummary>);
    let (delete_target, set_delete_target) = signal(None::<DatasetSummary>);
    let (name_input, set_name_input) = signal(String::new());
    let (busy, set_busy) = signal(false);
    let file_input_ref = NodeRef::<leptos::html::Input>::new();

    // NOTE: signal writes after an `.await` use the `try_*` variants — the
    // page can unmount while a request is in flight (see training_view.rs).
    let refresh = move || {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::list_datasets().await {
                Ok(r) => {
                    let _ = set_datasets.try_set(r.datasets);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_load_datasets, err = e));
                }
            }
            let _ = set_loading.try_set(false);
        });
    };
    refresh();

    spawn_local(async move {
        if let Ok(j) = api::get_training_status().await {
            if job_is_active(&j.status) {
                let _ = set_training_ds.try_set(j.dataset_id);
            }
        }
    });

    // ── create ────────────────────────────────────────────────────────────────

    let on_create = Callback::new(move |_: ()| {
        let name = name_input.get_untracked().trim().to_string();
        if name.is_empty() {
            set_error_msg.set(t_string!(i18n, training::type_dataset_name_first).to_string());
            return;
        }
        if busy.get_untracked() {
            return;
        }
        set_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::create_dataset(&name).await {
                Ok(meta) => {
                    let _ = set_show_create.try_set(false);
                    let _ = set_busy.try_set(false);
                    on_open.run(meta);
                    return;
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_create_dataset, err = e));
                }
            }
            let _ = set_busy.try_set(false);
        });
    });

    // ── upload ────────────────────────────────────────────────────────────────

    let on_upload = Callback::new(move |_: ()| {
        let name = name_input.get_untracked().trim().to_string();
        if name.is_empty() {
            set_error_msg.set(t_string!(i18n, training::type_dataset_name_first).to_string());
            return;
        }
        let Some(input) = file_input_ref.get_untracked() else {
            return;
        };
        let input = input.unchecked_ref::<web_sys::HtmlInputElement>().clone();
        let Some(file) = input.files().and_then(|fs| fs.get(0)) else {
            set_error_msg.set(t_string!(i18n, training::choose_zip_first).to_string());
            return;
        };
        if !file.name().to_lowercase().ends_with(".zip") {
            set_error_msg.set(t_string!(i18n, training::dataset_must_be_zip).to_string());
            return;
        }
        if busy.get_untracked() {
            return;
        }
        set_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::upload_dataset_zip(file, &name).await {
                Ok(r) => {
                    let _ = set_show_upload.try_set(false);
                    input.set_value("");
                    let _ = set_success_msg.try_set(
                        r.dataset
                            .map(|d| td_string!(locale, training::dataset_imported, name = d.name))
                            .unwrap_or_else(|| {
                                td_string!(locale, training::dataset_imported_generic).to_string()
                            }),
                    );
                    refresh();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::dataset_import_failed, err = e));
                }
            }
            let _ = set_busy.try_set(false);
        });
    });

    // ── export ────────────────────────────────────────────────────────────────

    // Programmatic anchor click: the browser drives the download (filename
    // comes from the gateway's Content-Disposition).
    let on_export = Callback::new(move |ds: DatasetSummary| {
        let url = api::training_dataset_export_url(&ds.dataset_id);
        let Some(document) = web_sys::window().and_then(|w| w.document()) else {
            return;
        };
        let Ok(anchor) = document.create_element("a") else {
            set_error_msg.set(t_string!(i18n, training::download_failed).to_string());
            return;
        };
        let _ = anchor.set_attribute("href", &url);
        let _ = anchor.set_attribute("download", &format!("{}.zip", ds.name));
        anchor.unchecked_ref::<web_sys::HtmlElement>().click();
    });

    // ── rename / delete ───────────────────────────────────────────────────────

    let on_rename = Callback::new(move |_: ()| {
        let Some(target) = rename_target.get_untracked() else {
            return;
        };
        let name = name_input.get_untracked().trim().to_string();
        if name.is_empty() {
            set_error_msg.set(t_string!(i18n, training::type_dataset_name_first).to_string());
            return;
        }
        if busy.get_untracked() {
            return;
        }
        set_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::rename_dataset(&target.dataset_id, &name).await {
                Ok(_) => {
                    let _ = set_rename_target.try_set(None);
                    refresh();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_rename_dataset, err = e));
                }
            }
            let _ = set_busy.try_set(false);
        });
    });

    let on_delete = Callback::new(move |_: ()| {
        let Some(target) = delete_target.get_untracked() else {
            return;
        };
        if busy.get_untracked() {
            return;
        }
        set_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::delete_dataset(&target.dataset_id).await {
                Ok(_) => {
                    let _ = set_delete_target.try_set(None);
                    let _ = set_success_msg
                        .try_set(td_string!(locale, training::dataset_deleted, name = target.name));
                    refresh();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_delete_dataset, err = e));
                }
            }
            let _ = set_busy.try_set(false);
        });
    });

    view! {
        <div class="ui-card ui-card-pad flex flex-col gap-4">
            <div class="flex items-center justify-between">
                <h2 class="ui-card-title">{t!(i18n, training::datasets_title)}</h2>
                <div class="flex items-center gap-2">
                    <button
                        class="ui-button ui-button-neutral ui-button-md"
                        on:click=move |_| {
                            set_name_input.set(String::new());
                            set_show_upload.set(true);
                        }
                    >
                        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                        </svg>
                        {t!(i18n, training::upload_dataset)}
                    </button>
                    <button
                        class="ui-button ui-button-success ui-button-md"
                        on:click=move |_| {
                            set_name_input.set(String::new());
                            set_show_create.set(true);
                        }
                    >
                        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                        </svg>
                        {t!(i18n, training::new_dataset)}
                    </button>
                </div>
            </div>

            {move || {
                let items = datasets.get();
                if loading.get() {
                    view! { <p class="ui-help italic">{t_string!(i18n, training::loading_datasets)}</p> }.into_any()
                } else if items.is_empty() {
                    view! {
                        <p class="ui-help italic">
                            {t_string!(i18n, training::no_datasets_yet)}
                        </p>
                    }.into_any()
                } else {
                    view! {
                        <div class="ui-dataset-grid">
                            <For
                                each=move || datasets.get()
                                key=|ds| (ds.dataset_id.clone(), ds.name.clone(),
                                          ds.cover_image_id.clone(), ds.image_count)
                                children=move |ds: DatasetSummary| {
                                    let ds_id = ds.dataset_id.clone();
                                    let training =
                                        Signal::derive(move || training_ds.get() == ds_id);
                                    view! {
                                        <DatasetCard
                                            dataset=ds
                                            training=training
                                            on_open=on_open
                                            on_export=on_export
                                            on_rename=Callback::new(move |ds: DatasetSummary| {
                                                set_name_input.set(ds.name.clone());
                                                set_rename_target.set(Some(ds));
                                            })
                                            on_delete=Callback::new(move |ds: DatasetSummary| {
                                                set_delete_target.set(Some(ds));
                                            })
                                        />
                                    }
                                }
                            />
                        </div>
                    }.into_any()
                }
            }}

            <DatasetNameModal
                title=move || t_string!(i18n, training::new_dataset)
                cta=move || t_string!(i18n, training::create)
                busy_label=move || t_string!(i18n, training::creating)
                visible=Signal::derive(move || show_create.get())
                name=name_input
                set_name=set_name_input
                busy=busy
                on_submit=on_create
                on_cancel=Callback::new(move |_| set_show_create.set(false))
            />

            <DatasetUploadModal
                visible=show_upload
                name=name_input
                set_name=set_name_input
                busy=busy
                file_input_ref=file_input_ref
                on_submit=on_upload
                on_cancel=Callback::new(move |_| set_show_upload.set(false))
            />

            <DatasetNameModal
                title=move || t_string!(i18n, training::rename_dataset)
                cta=move || t_string!(i18n, training::rename)
                busy_label=move || t_string!(i18n, training::renaming)
                visible=Signal::derive(move || rename_target.get().is_some())
                name=name_input
                set_name=set_name_input
                busy=busy
                on_submit=on_rename
                on_cancel=Callback::new(move |_| set_rename_target.set(None))
            />

            <DatasetDeleteModal
                target=delete_target
                busy=busy
                on_confirm=on_delete
                on_cancel=Callback::new(move |_| set_delete_target.set(None))
            />
        </div>
    }
}
