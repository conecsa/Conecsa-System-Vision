//! Leptos UI components for the web frontend.

use crate::api;
use crate::app::{load_models, ModelInfo};
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;
use wasm_bindgen::JsCast;

use crate::components::configuration::model_conversion::{
    poll_conversion_job, ConversionPollConfig,
};

use js_sys::Date;

use super::context_menu::ModelContextMenu;
use super::model_list::ModelList;
use super::section_header::ModelSectionHeader;

/// The `DetectionModels` view component.
#[component]
pub fn DetectionModels(
    models: ReadSignal<Vec<ModelInfo>>,
    set_models: WriteSignal<Vec<ModelInfo>>,
    // Bumped after a successful model select so all per-model state
    // (detection areas, thresholds, classes) is refreshed on screen.
    set_model_refresh: WriteSignal<u32>,
    // Overlay signals are owned by Configuration so the overlay can cover the full panel
    set_active_job_id: WriteSignal<Option<String>>,
    set_overlay_message: WriteSignal<String>,
    set_overlay_progress: WriteSignal<u8>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let file_input_ref = NodeRef::<leptos::html::Input>::new();

    // State for context menu
    let (context_menu_visible, set_context_menu_visible) = signal(false);
    let (context_menu_x, set_context_menu_x) = signal(0);
    let (context_menu_y, set_context_menu_y) = signal(0);
    let (selected_model_for_delete, set_selected_model_for_delete) = signal(String::new());

    // On mount, recover any in-progress conversion that was running before a page refresh
    let mount_locale = i18n.get_locale_untracked();
    spawn_local(async move {
        if let Ok(resp) = api::list_active_conversions().await {
            if let Some(job) = resp.jobs.into_iter().next() {
                let job_id = job.job_id.clone();
                let orig_file = job.original_filename.clone();

                let now_secs = Date::now() / 1000.0;
                let started_at_secs = job.started_at.unwrap_or(now_secs);
                let elapsed = now_secs - started_at_secs;

                // Already timed-out - do not show overlay
                if elapsed > 660.0 {
                    set_error_msg.set(
                        td_string!(mount_locale, models::previous_conversion_timed_out)
                            .to_string(),
                    );
                    return;
                }

                let time_progress = ((elapsed / 420.0) * 100.0).min(95.0) as u8;
                set_active_job_id.set(Some(job_id.clone()));
                set_overlay_message.set(job.message.clone());
                set_overlay_progress.set(time_progress);

                poll_conversion_job(
                    ConversionPollConfig {
                        job_id,
                        started_at_secs,
                        original_filename: orig_file,
                        timeout_secs: 660.0,
                        progress_cap: 95.0,
                        locale: mount_locale,
                    },
                    set_active_job_id,
                    set_overlay_message,
                    set_overlay_progress,
                    set_success_msg,
                    set_error_msg,
                    set_models,
                    set_model_refresh,
                )
                .await;
            }
        }
    });

    let upload_model = Callback::new(move |_| {
        if let Some(input) = file_input_ref.get() {
            input.click();
        }
    });

    // Name of the active model (the one shown as selected in the list).
    let active_model: Signal<Option<String>> = Signal::derive(move || {
        models
            .get()
            .iter()
            .find(|m| m.is_active)
            .map(|m| m.name.clone())
    });

    // Programmatic anchor click: the browser drives the download (filename
    // comes from the gateway's Content-Disposition).
    let download_model = Callback::new(move |_: ()| {
        let locale = i18n.get_locale_untracked();
        let Some(name) = active_model.get_untracked() else {
            return;
        };
        let url = api::model_download_url(&name);
        let Some(document) = web_sys::window().and_then(|w| w.document()) else {
            return;
        };
        let Ok(anchor) = document.create_element("a") else {
            set_error_msg.set(td_string!(locale, models::could_not_start_download).to_string());
            return;
        };
        let _ = anchor.set_attribute("href", &url);
        let _ = anchor.set_attribute("download", &name);
        anchor.unchecked_ref::<web_sys::HtmlElement>().click();
        // The browser saves without a path picker, so tell the user where.
        set_success_msg.set(td_string!(locale, models::downloading_to_folder, name = name));
    });

    let on_file_change = move |_| {
        let locale = i18n.get_locale_untracked();
        if let Some(input) = file_input_ref.get() {
            let input_element = input.unchecked_ref::<web_sys::HtmlInputElement>();

            if let Some(files) = input_element.files() {
                if let Some(file) = files.get(0) {
                    let file_name = file.name();

                    let allowed_extensions = [".pt", ".onnx", ".engine", ".plan"];
                    // Temporary local variant that also accepted .pt intentionally disabled.
                    // let allowed_extensions = [".pt", ".onnx", ".engine", ".plan"];
                    // Deprecated formats intentionally rejected in TensorRT-only mode.
                    // let allowed_extensions = [".tflite", ".pt", ".onnx", ".h5", ".engine", ".plan"];
                    let has_valid_ext = allowed_extensions
                        .iter()
                        .any(|ext| file_name.ends_with(ext));

                    if !has_valid_ext {
                        set_error_msg.set(td_string!(
                            locale,
                            models::invalid_file_type_allowed,
                            exts = allowed_extensions.join(", ")
                        ));
                        input_element.set_value("");
                        return;
                    }

                    set_active_job_id.set(Some("uploading".to_string()));
                    set_overlay_message.set(td_string!(
                        locale,
                        models::uploading_file,
                        name = file_name.clone()
                    ));
                    set_overlay_progress.set(0);

                    spawn_local(async move {
                        match api::upload_model_file(file).await {
                            Ok(resp) if resp.status == "converting" => {
                                if let Some(job_id) = resp.job_id.clone() {
                                    set_active_job_id.set(Some(job_id.clone()));

                                    let started_at_secs: f64 = {
                                        let sa = api::get_conversion_status(&job_id)
                                            .await
                                            .ok()
                                            .and_then(|s| {
                                                set_overlay_message.set(s.message.clone());
                                                s.started_at
                                            });
                                        sa.unwrap_or_else(|| Date::now() / 1000.0)
                                    };

                                    poll_conversion_job(
                                        ConversionPollConfig {
                                            job_id,
                                            started_at_secs,
                                            original_filename: file_name,
                                            timeout_secs: 600.0,
                                            progress_cap: 90.0,
                                            locale,
                                        },
                                        set_active_job_id,
                                        set_overlay_message,
                                        set_overlay_progress,
                                        set_success_msg,
                                        set_error_msg,
                                        set_models,
                                        set_model_refresh,
                                    )
                                    .await;
                                } else {
                                    set_active_job_id.set(None);
                                    set_error_msg.set(
                                        td_string!(locale, models::upload_no_job_id).to_string(),
                                    );
                                }
                            }
                            Ok(_) => {
                                set_active_job_id.set(None);
                                set_success_msg.set(td_string!(
                                    locale,
                                    models::model_uploaded,
                                    name = file_name
                                ));
                                load_models(set_models, set_error_msg, locale).await;
                                set_model_refresh.update(|n| *n = n.wrapping_add(1));
                            }
                            Err(e) => {
                                set_active_job_id.set(None);
                                set_error_msg.set(td_string!(
                                    locale,
                                    models::failed_to_upload_model,
                                    err = e
                                ));
                            }
                        }
                    });

                    input_element.set_value("");
                }
            }
        }
    };

    /// A `ModelOp` enum.
    enum ModelOp {
        Select,
        Delete,
    }

    let handle_model = move |op: ModelOp, model_name: String| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            let result: Result<(ModelOp, String), String> = match op {
                ModelOp::Select => api::select_model(&model_name)
                    .await
                    .map(|_| {
                        (
                            ModelOp::Select,
                            td_string!(locale, models::model_selected, name = model_name.clone()),
                        )
                    })
                    .map_err(|e| td_string!(locale, models::failed_to_select_model, err = e)),
                ModelOp::Delete => api::delete_model(&model_name)
                    .await
                    .map(|_| {
                        (
                            ModelOp::Delete,
                            td_string!(locale, models::model_deleted, name = model_name.clone()),
                        )
                    })
                    .map_err(|e| td_string!(locale, models::failed_to_delete_model, err = e)),
            };
            match result {
                Ok((completed_op, msg)) => {
                    set_success_msg.set(msg);
                    load_models(set_models, set_error_msg, locale).await;
                    if matches!(completed_op, ModelOp::Select) {
                        set_model_refresh.update(|n| *n = n.wrapping_add(1));
                    }
                }
                Err(e) => set_error_msg.set(e),
            }
        });
    };

    let select_model_handler =
        Callback::new(move |model_name: String| handle_model(ModelOp::Select, model_name));
    let delete_model_handler =
        Callback::new(move |model_name: String| handle_model(ModelOp::Delete, model_name));

    let confirm_delete = Callback::new(move |_| {
        let model_name = selected_model_for_delete.get();
        if !model_name.is_empty() {
            delete_model_handler.run(model_name);
        }
        set_context_menu_visible.set(false);
    });

    let privileged = crate::components::access::privileged();

    view! {
        <div
            class="flex-1 flex flex-col min-h-0"
            on:click=move |_| {
                if context_menu_visible.get() {
                    set_context_menu_visible.set(false);
                }
            }
        >
            // Hidden file input for browser-based model upload
            <input
                type="file"
                accept="*.pt,*.onnx,*.engine,*.plan"
                // Legacy accept values intentionally disabled in TensorRT-only mode.
                // accept=".tflite,.pt,.onnx,.h5,.engine,.plan"
                disabled=!privileged
                node_ref=file_input_ref
                on:change=on_file_change
                style="display: none;"
            />

            <ModelSectionHeader active_model=active_model on_download=download_model on_upload=upload_model />

            <ModelList
                models=models
                on_select=select_model_handler
                set_context_menu_x=set_context_menu_x
                set_context_menu_y=set_context_menu_y
                set_selected_model_for_delete=set_selected_model_for_delete
                set_context_menu_visible=set_context_menu_visible
                set_error_msg=set_error_msg
            />

            <ModelContextMenu
                visible=context_menu_visible
                x=context_menu_x
                y=context_menu_y
                on_confirm_delete=confirm_delete
            />
        </div>
    }
}
