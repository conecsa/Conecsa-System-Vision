//! Leptos UI components for the web frontend.

use gloo_timers::future::TimeoutFuture;
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;
use crate::app::{check_api_health, refresh_status, SystemStatus};
use crate::components::configuration::model_conversion::PendingConversion;
use crate::components::control_panel::ViewMode;
use crate::components::training::{TrainingConfirmModal, TrainingView};
use crate::i18n::*;
use crate::models::PerformanceStats;

use super::main_component::MainComponent;

/// The `MainView` view component.
#[component]
pub fn MainView() -> impl IntoView {
    let i18n = use_i18n();
    let (status, set_status) = signal(None::<SystemStatus>);
    let (stats, set_stats) = signal(None::<PerformanceStats>);
    let (models, set_models) = signal(Vec::new());
    let (threshold, set_threshold) = signal(0.75_f32);
    let (overlay_threshold, set_overlay_threshold) = signal(0.45_f32);
    let (error_msg, set_error_msg) = signal(String::new());
    let (success_msg, set_success_msg) = signal(String::new());
    let (api_health, set_api_health) = signal(false);
    let (info_view, set_info_view) = signal(None::<String>);
    let (current_view, set_current_view) = signal(ViewMode::LiveStream);
    // Bumped after a model select so model-scoped state (detection areas,
    // thresholds) is refreshed across sibling panels.
    let (model_refresh, set_model_refresh) = signal(0u32);
    let (camera_refresh, set_camera_refresh) = signal(0u32);
    let (network_refresh, set_network_refresh) = signal(0u32);
    let (gpio_refresh, set_gpio_refresh) = signal(0u32);
    // Training page entry is confirmed (it stops inference); on training
    // completion the resulting conversion job is handed to Configuration.
    let (show_training_confirm, set_show_training_confirm) = signal(false);
    let (pending_conversion, set_pending_conversion) = signal(None::<PendingConversion>);
    // Set by Configuration while any model conversion runs; disables Start
    // Detection so the GPU stays free for the TensorRT engine build.
    let (converting, set_converting) = signal(false);

    // Load initial data
    spawn_local(async move {
        refresh_status(set_status, set_error_msg).await;
        check_api_health(set_api_health).await;
    });

    // Auto-refresh status and API health every 5 seconds. The high-frequency
    // PerformanceStats fields are pushed in real time via SSE below, so this
    // loop only covers the slow-changing fields (active model, is_running,
    // thresholds).
    let refresh_interval = move || {
        spawn_local(async move {
            loop {
                TimeoutFuture::new(5000).await;
                refresh_status(set_status, set_error_msg).await;
                check_api_health(set_api_health).await;
            }
        });
    };

    Effect::new(move |_| {
        refresh_interval();
    });

    // Unified application stream: ONE SSE connection per page load carrying
    // both invalidation events and high-rate performance stats. Any client can
    // change backend state (web UI, Node-RED, curl), so this reconciles the
    // mounted UI with authoritative backend reads whenever a relevant event
    // arrives; stats (`type: "stats"`) feed the dedicated `stats` signal in
    // real time. The handle is leaked on purpose — the connection should live
    // for the entire MainView lifetime, and the browser closes the EventSource
    // automatically on page unload.
    Effect::new(move |_| {
        match api::subscribe_app_events(move |event| {
            // High-rate stats channel multiplexed onto the same stream.
            if event.event_type == "stats" {
                match serde_json::from_value::<PerformanceStats>(event.data.clone()) {
                    Ok(s) => set_stats.set(Some(s)),
                    Err(e) => leptos::logging::error!("Failed to parse stats event: {}", e),
                }
                return;
            }

            let is_snapshot = event.event_type == "state_snapshot";
            let has_key = |key: &str| event.keys.iter().any(|k| k == key);

            if is_snapshot || has_key("models") {
                let locale = i18n.get_locale_untracked();
                spawn_local(async move {
                    crate::app::load_models(set_models, set_error_msg, locale).await;
                });
            }

            if is_snapshot || has_key("status") || has_key("thresholds") {
                spawn_local(async move {
                    refresh_status(set_status, set_error_msg).await;
                });
            }

            if is_snapshot || has_key("classes") || has_key("areas") {
                set_model_refresh.update(|n| *n = n.wrapping_add(1));
            }

            if is_snapshot || has_key("camera") {
                set_camera_refresh.update(|n| *n = n.wrapping_add(1));
            }

            if is_snapshot || has_key("network") {
                set_network_refresh.update(|n| *n = n.wrapping_add(1));
            }

            if is_snapshot || has_key("gpio") {
                set_gpio_refresh.update(|n| *n = n.wrapping_add(1));
            }
        }) {
            Ok(handle) => std::mem::forget(handle),
            Err(e) => leptos::logging::error!("Failed to open app event SSE: {}", e),
        }
    });

    // Keep threshold sliders synced with backend values (including external changes).
    Effect::new(move |_| {
        if let Some(status) = status.get() {
            set_threshold.set(status.confidence_threshold);
            set_overlay_threshold.set(status.overlay_threshold);
        }
    });

    // After a model select, refresh status immediately so the per-model
    // thresholds reflect on screen without waiting for the 5s poll. Detection
    // areas are refreshed by LiveVideoStream, which also watches model_refresh;
    // classes are refreshed by Configuration, which also watches it.
    Effect::new(move |prev: Option<u32>| {
        let key = model_refresh.get();
        // Skip the initial run (mount already fetches status).
        if prev.is_some() {
            spawn_local(async move {
                refresh_status(set_status, set_error_msg).await;
            });
        }
        key
    });

    // When the backend transitions from unreachable to healthy (cold start or
    // a backend restart), it has just restored the persisted model and its
    // per-model settings. Bump model_refresh so every per-model value
    // (thresholds, detection areas, classes) reloads — the one-shot mount
    // fetches would otherwise have run before the backend was ready, leaving
    // stale defaults until a manual reload or model re-select.
    Effect::new(move |was_healthy: Option<bool>| {
        let healthy = api_health.get();
        if was_healthy == Some(false) && healthy {
            set_model_refresh.update(|n| *n = n.wrapping_add(1));
        }
        healthy
    });

    let on_training_request = Callback::new(move |_| {
        // Training releases the GPU runtime, which would interrupt an
        // in-progress engine build — the backend's ReleaseRuntime refuses
        // during a conversion anyway, so block here and explain why.
        if converting.get_untracked() {
            let locale = i18n.get_locale_untracked();
            set_error_msg
                .set(td_string!(locale, main::conversion_wait_before_training).to_string());
            return;
        }
        set_show_training_confirm.set(true);
    });

    // Only the Training/non-Training distinction should swap the top-level view.
    // A `Memo` notifies only when this boolean actually flips, so navigating
    // among the dashboard views (Live/Camera/Flow/Settings) does NOT recreate
    // `MainComponent` (and thus does not remount long-lived children like
    // StatusComponent). Within MainComponent, the primary pane still switches
    // per `current_view`.
    let is_training = Memo::new(move |_| current_view.get() == ViewMode::Training);

    view! {
        {move || if is_training.get() {
            view! {
                <TrainingView
                    set_current_view=set_current_view
                    set_pending_conversion=set_pending_conversion
                />
            }.into_any()
        } else {
            view! {
                <MainComponent
                    status=status
                    set_status=set_status
                    stats=stats
                    models=models
                    set_models=set_models
                    threshold=threshold
                    set_threshold=set_threshold
                    overlay_threshold=overlay_threshold
                    set_overlay_threshold=set_overlay_threshold
                    error_msg=error_msg
                    set_error_msg=set_error_msg
                    success_msg=success_msg
                    set_success_msg=set_success_msg
                    api_health=api_health
                    info_view=info_view
                    set_info_view=set_info_view
                    current_view=current_view
                    set_current_view=set_current_view
                    model_refresh=model_refresh
                    set_model_refresh=set_model_refresh
                    camera_refresh=camera_refresh
                    network_refresh=network_refresh
                    gpio_refresh=gpio_refresh
                    on_training_request=on_training_request
                    external_conversion=pending_conversion
                    converting=converting
                    set_converting=set_converting
                />
            }.into_any()
        }}

        <TrainingConfirmModal
            visible=show_training_confirm
            set_visible=set_show_training_confirm
            set_current_view=set_current_view
            set_error_msg=set_error_msg
        />
    }
}
