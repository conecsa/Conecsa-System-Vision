//! Leptos UI components for the web frontend.

use crate::api;
use crate::app::{load_models, refresh_status, ModelInfo, SystemStatus};
use crate::components::class_names::ClassNames;
use crate::components::detection_models::DetectionModels;
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::conversion_overlay::ConversionOverlay;
use super::model_conversion;
use super::threshold_slider::ThresholdSlider;

/// The `Configuration` view component.
#[component]
pub fn Configuration(
    _status: ReadSignal<Option<SystemStatus>>,
    models: ReadSignal<Vec<ModelInfo>>,
    set_models: WriteSignal<Vec<ModelInfo>>,
    threshold: ReadSignal<f32>,
    set_threshold: WriteSignal<f32>,
    overlay_threshold: ReadSignal<f32>,
    set_overlay_threshold: WriteSignal<f32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
    set_status: WriteSignal<Option<SystemStatus>>,
    // Per-model refresh trigger (owned by MainView). Bumped on model select
    // and when the backend becomes healthy; we fan it out to the classes
    // re-fetch below so per-model classes reload alongside areas/thresholds.
    model_refresh: ReadSignal<u32>,
    set_model_refresh: WriteSignal<u32>,
    /// Conversion started elsewhere (the training-service uploading its
    /// trained model). When set, the standard overlay + poll attach to it —
    /// same UX as a manual .pt upload.
    external_conversion: ReadSignal<Option<model_conversion::PendingConversion>>,
    /// Mirrors "a conversion is in progress" up to the control panel so it can
    /// disable Start Detection while the engine is being built.
    set_converting: WriteSignal<bool>,
) -> impl IntoView {
    let i18n = use_i18n();
    // State for loading / conversion overlay — owned here so the overlay covers the full panel
    let (active_job_id, set_active_job_id) = signal(Option::<String>::None);
    let (overlay_message, set_overlay_message) = signal(String::new());
    let (overlay_progress, set_overlay_progress) = signal(0u8);

    // A job id is set for the whole duration of any conversion (manual upload
    // or training handoff) and cleared when it finishes.
    Effect::new(move |_| set_converting.set(active_job_id.get().is_some()));

    Effect::new(move |_| {
        let Some(pc) = external_conversion.get() else {
            return;
        };
        if active_job_id.get_untracked().is_some() {
            return;
        }
        let locale = i18n.get_locale_untracked();
        set_active_job_id.set(Some(pc.job_id.clone()));
        set_overlay_message.set(td_string!(
            locale,
            models::converting_to_engine,
            name = pc.filename.clone()
        ));
        set_overlay_progress.set(0);
        spawn_local(async move {
            model_conversion::poll_conversion_job(
                model_conversion::ConversionPollConfig {
                    job_id: pc.job_id,
                    started_at_secs: pc.started_at_secs,
                    original_filename: pc.filename,
                    timeout_secs: 660.0,
                    progress_cap: 95.0,
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
        });
    });

    // Trigger that ClassNames watches: incrementing it causes a re-fetch of
    // the active model's classes. Driven by the per-model `model_refresh`
    // trigger (model select / backend-healthy) via the Effect below.
    let (refresh_classes, set_refresh_classes) = signal(0u32);

    // Fan `model_refresh` out to the classes re-fetch. Skip the initial run —
    // ClassNames already fetches on mount.
    Effect::new(move |prev: Option<u32>| {
        let key = model_refresh.get();
        if prev.is_some() {
            set_refresh_classes.update(|n| *n = n.wrapping_add(1));
        }
        key
    });

    // Load models on mount
    let mount_locale = i18n.get_locale_untracked();
    spawn_local(async move {
        load_models(set_models, set_error_msg, mount_locale).await;
    });

    let update_threshold = Callback::new(move |val: f32| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::set_threshold(val).await {
                Ok(_) => {
                    set_success_msg.set(td_string!(
                        locale,
                        models::threshold_set,
                        value = format!("{:.2}", val)
                    ));
                    refresh_status(set_status, set_error_msg).await;
                }
                Err(e) => set_error_msg.set(td_string!(
                    locale,
                    models::failed_to_set_threshold,
                    err = e
                )),
            }
        });
    });

    let update_overlay_threshold = Callback::new(move |val: f32| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::set_overlay_threshold(val).await {
                Ok(_) => {
                    set_success_msg.set(td_string!(
                        locale,
                        models::overlay_threshold_set,
                        value = format!("{:.2}", val)
                    ));
                    refresh_status(set_status, set_error_msg).await;
                }
                Err(e) => set_error_msg.set(td_string!(
                    locale,
                    models::failed_to_set_overlay_threshold,
                    err = e
                )),
            }
        });
    });

    view! {
        <div class="ui-card ui-card-pad h-full flex flex-col relative">
            <ConversionOverlay
                active_job_id=active_job_id
                message=overlay_message
                progress=overlay_progress
            />

            // ===== Configuration Header =====
            <PanelHeader
                title=move || t_string!(i18n, models::configuration_title)
                trailing=view! {
                    <div class="flex items-center gap-2">
                        <span class="ui-label-xs">{t!(i18n, models::runtime_label)}</span>
                        <span class="ui-badge ui-badge-primary normal-case">
                            "TensorRT"
                        </span>
                    </div>
                }.into_any()
            >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </PanelHeader>

            // ===== Confidence Threshold Section =====
            <ThresholdSlider
                label=move || t_string!(i18n, models::confidence_threshold)
                description=move || t_string!(i18n, models::confidence_threshold_desc)
                value=threshold
                set_value=set_threshold
                on_change=update_threshold
            />

            // ===== Overlay Threshold Section =====
            <ThresholdSlider
                label=move || t_string!(i18n, models::overlay_threshold)
                description=move || t_string!(i18n, models::overlay_threshold_desc)
                value=overlay_threshold
                set_value=set_overlay_threshold
                on_change=update_overlay_threshold
            />

            // ===== Class Names Section =====
            <ClassNames
                refresh_classes=refresh_classes
                set_error_msg=set_error_msg
                set_success_msg=set_success_msg
            />

            // ===== Detection Models Section =====
            <DetectionModels
                models=models
                set_models=set_models
                set_model_refresh=set_model_refresh
                set_active_job_id=set_active_job_id
                set_overlay_message=set_overlay_message
                set_overlay_progress=set_overlay_progress
                set_error_msg=set_error_msg
                set_success_msg=set_success_msg
            />
        </div>
    }
}
