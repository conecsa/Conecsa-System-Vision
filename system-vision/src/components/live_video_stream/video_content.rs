//! Leptos UI components for the web frontend.

use super::camera_disconnected_state::CameraDisconnectedState;
use super::detection_stopped_state::DetectionStoppedState;
use super::loading_stream_state::LoadingStreamState;
use super::running_stream::RunningStream;
use crate::app::SystemStatus;
use crate::components::area_chips::AreaView;
use leptos::prelude::*;

#[component]
pub(super) fn VideoContent(
    status: ReadSignal<Option<SystemStatus>>,
    set_info_view: WriteSignal<Option<String>>,
    reload_key: ReadSignal<u32>,
    set_reload_key: WriteSignal<u32>,
    areas: ReadSignal<Vec<AreaView>>,
    panel: RwSignal<u8>,
    model_refresh: ReadSignal<u32>,
    camera_refresh: ReadSignal<u32>,
    editing_id: Signal<Option<String>>,
    editing_shape: Signal<String>,
    on_add: Callback<()>,
    on_edit_chip: Callback<String>,
    on_delete_chip: Callback<String>,
    on_command: Callback<&'static str>,
    on_toggle_shape: Callback<()>,
    on_save: Callback<()>,
    on_cancel: Callback<()>,
) -> impl IntoView {
    view! {
        <div class="ui-list-box flex items-center justify-center p-4 flex-1 min-h-0 overflow-hidden">
            {move || {
                if let Some(s) = status.get() {
                    set_info_view.set(None);
                    if !s.camera_connected {
                        // No camera → the webcam-server publishes no frames at
                        // all, so there is nothing to stream even if detection
                        // is still flagged as running.
                        view! { <CameraDisconnectedState /> }.into_any()
                    } else if s.is_running {
                        view! {
                            <RunningStream
                                reload_key=reload_key
                                set_reload_key=set_reload_key
                                areas=areas
                                panel=panel
                                model_refresh=model_refresh
                                camera_refresh=camera_refresh
                                editing_id=editing_id
                                editing_shape=editing_shape
                                on_add=on_add
                                on_edit_chip=on_edit_chip
                                on_delete_chip=on_delete_chip
                                on_command=on_command
                                on_toggle_shape=on_toggle_shape
                                on_save=on_save
                                on_cancel=on_cancel
                            />
                        }.into_any()
                    } else {
                        view! { <DetectionStoppedState /> }.into_any()
                    }
                } else {
                    view! { <LoadingStreamState /> }.into_any()
                }
            }}
        </div>
    }
}
