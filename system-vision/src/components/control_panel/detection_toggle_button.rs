//! Leptos UI components for the web frontend.

use crate::app::SystemStatus;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn DetectionToggleButton(
    status: ReadSignal<Option<SystemStatus>>,
    /// True while a model is being converted/optimized — Start is disabled so
    /// detection cannot run on the GPU during the TensorRT build.
    converting: ReadSignal<bool>,
    on_start: Callback<()>,
    on_stop: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="mb-4">
            {move || {
                let snapshot = status.get();
                let is_running = snapshot.as_ref().map(|s| s.is_running).unwrap_or(false);
                let no_camera = snapshot.map(|s| !s.camera_connected).unwrap_or(false);
                let is_converting = converting.get();
                if is_running {
                    view! {
                        <button class="ui-button ui-button-danger ui-button-md w-full" on:click=move |_| on_stop.run(())>
                            <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                                <rect x="6" y="6" width="12" height="12" stroke-width="2"/>
                            </svg>
                            {t_string!(i18n, control_panel::stop_detection)}
                        </button>
                    }.into_any()
                } else {
                    view! {
                        <button
                            class="ui-button ui-button-success ui-button-md w-full disabled:opacity-50 disabled:cursor-not-allowed"
                            disabled=is_converting || no_camera
                            title=if is_converting {
                                t_string!(i18n, control_panel::wait_conversion)
                            } else if no_camera {
                                t_string!(i18n, control_panel::camera_disconnected)
                            } else { "" }
                            on:click=move |_| on_start.run(())
                        >
                            <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                                <polygon points="5 3 19 12 5 21 5 3" stroke-width="2"/>
                            </svg>
                            {if is_converting {
                                t_string!(i18n, control_panel::converting_model)
                            } else if no_camera {
                                t_string!(i18n, control_panel::camera_disconnected)
                            } else {
                                t_string!(i18n, control_panel::start_detection)
                            }}
                        </button>
                    }.into_any()
                }
            }}
        </div>
    }
}
