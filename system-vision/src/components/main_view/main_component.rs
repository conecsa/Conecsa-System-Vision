//! Leptos UI components for the web frontend.

use crate::app::{ModelInfo, SystemStatus};
use crate::components::configuration::model_conversion::PendingConversion;
use crate::components::{
    camera_settings::CameraSettings, control_panel::ViewMode, Configuration, ControlPanel, Flow,
    Header, LiveVideoStream, PerformanceStatistics, PopupMessages, Settings, StatusComponent,
    ViewNavigation,
};
use crate::models::PerformanceStats;
use leptos::prelude::*;

#[component]
pub(super) fn MainComponent(
    status: ReadSignal<Option<SystemStatus>>,
    set_status: WriteSignal<Option<SystemStatus>>,
    stats: ReadSignal<Option<PerformanceStats>>,
    models: ReadSignal<Vec<ModelInfo>>,
    set_models: WriteSignal<Vec<ModelInfo>>,
    threshold: ReadSignal<f32>,
    set_threshold: WriteSignal<f32>,
    overlay_threshold: ReadSignal<f32>,
    set_overlay_threshold: WriteSignal<f32>,
    error_msg: ReadSignal<String>,
    set_error_msg: WriteSignal<String>,
    success_msg: ReadSignal<String>,
    set_success_msg: WriteSignal<String>,
    api_health: ReadSignal<bool>,
    info_view: ReadSignal<Option<String>>,
    set_info_view: WriteSignal<Option<String>>,
    current_view: ReadSignal<ViewMode>,
    set_current_view: WriteSignal<ViewMode>,
    model_refresh: ReadSignal<u32>,
    set_model_refresh: WriteSignal<u32>,
    camera_refresh: ReadSignal<u32>,
    network_refresh: ReadSignal<u32>,
    gpio_refresh: ReadSignal<u32>,
    on_training_request: Callback<()>,
    external_conversion: ReadSignal<Option<PendingConversion>>,
    converting: ReadSignal<bool>,
    set_converting: WriteSignal<bool>,
) -> impl IntoView {
    view! {
        <div class="app-scale-viewport">
            <div class="app-scale-content">
                <div class="app-shell">
                    <Header api_health=api_health />

                    <div class="app-alert-slot">
                        <PopupMessages
                            error_msg=error_msg
                            success_msg=success_msg
                            info_view=info_view
                            set_error_msg=set_error_msg
                            set_success_msg=set_success_msg
                            _set_info_view=set_info_view
                        />
                    </div>

                    <main class="app-main">
                        <div class="app-dashboard-grid">
                            <div class="app-primary-pane">
                                {move || match current_view.get() {
                                    ViewMode::LiveStream => view! {
                                        <LiveVideoStream
                                            status=status
                                            set_info_view=set_info_view
                                            model_refresh=model_refresh
                                            camera_refresh=camera_refresh
                                        />
                                    }.into_any(),
                                    ViewMode::CameraSettings => view! {
                                        <CameraSettings
                                            refresh_camera=camera_refresh
                                            set_error_msg=set_error_msg
                                            set_success_msg=set_success_msg
                                        />
                                    }.into_any(),
                                    ViewMode::Flow => view! {
                                        <Flow />
                                    }.into_any(),
                                    ViewMode::Settings => view! {
                                        <Settings
                                            refresh_network=network_refresh
                                            refresh_gpio=gpio_refresh
                                            set_error_msg=set_error_msg
                                            set_success_msg=set_success_msg
                                        />
                                    }.into_any(),
                                    // Training replaces the whole dashboard;
                                    // MainView branches to TrainingView before
                                    // this component renders.
                                    ViewMode::Training => view! { <div/> }.into_any(),
                                }}
                            </div>

                            <div class="app-side-panel">
                                <Configuration
                                    _status=status
                                    models=models
                                    set_models=set_models
                                    threshold=threshold
                                    set_threshold=set_threshold
                                    overlay_threshold=overlay_threshold
                                    set_overlay_threshold=set_overlay_threshold
                                    set_error_msg=set_error_msg
                                    set_success_msg=set_success_msg
                                    set_status=set_status
                                    model_refresh=model_refresh
                                    set_model_refresh=set_model_refresh
                                    external_conversion=external_conversion
                                    set_converting=set_converting
                                />
                            </div>

                            <div class="app-side-panel">
                                <ViewNavigation
                                    current_view=current_view
                                    set_current_view=set_current_view
                                    on_training_request=on_training_request
                                />
                                <ControlPanel
                                    status=status
                                    set_status=set_status
                                    set_error_msg=set_error_msg
                                    set_success_msg=set_success_msg
                                    converting=converting
                                />
                                <div class="app-side-fill">
                                    <PerformanceStatistics stats=stats />
                                </div>
                            </div>

                            <div class="app-status-row">
                                <StatusComponent />
                            </div>
                        </div>
                    </main>
                </div>
            </div>
        </div>
    }
}
