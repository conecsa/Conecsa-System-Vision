//! Leptos UI components for the web frontend.

use crate::api;
use crate::app::{refresh_status, SystemStatus};
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::detection_toggle_button::DetectionToggleButton;
use super::status_summary::StatusSummary;

/// The `ControlPanel` view component.
#[component]
pub fn ControlPanel(
    status: ReadSignal<Option<SystemStatus>>,
    set_status: WriteSignal<Option<SystemStatus>>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
    /// True while a model conversion is running (disables Start Detection).
    converting: ReadSignal<bool>,
) -> impl IntoView {
    let i18n = use_i18n();

    let start_detection = Callback::new(move |_| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::start_detection().await {
                Ok(_) => {
                    set_success_msg
                        .set(td_string!(locale, control_panel::detection_started).to_string());
                    refresh_status(set_status, set_error_msg).await;
                }
                Err(e) => {
                    web_sys::console::log_1(&format!("Error starting detection: {}", e).into());
                    set_error_msg
                        .set(td_string!(locale, control_panel::failed_to_start, err = e));
                }
            }
        });
    });

    let stop_detection = Callback::new(move |_| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::stop_detection().await {
                Ok(_) => {
                    set_success_msg
                        .set(td_string!(locale, control_panel::detection_stopped).to_string());
                    refresh_status(set_status, set_error_msg).await;
                }
                Err(e) => {
                    set_error_msg.set(td_string!(locale, control_panel::failed_to_stop, err = e));
                }
            }
        });
    });

    view! {
        <div class="ui-card ui-card-pad flex flex-col">
            <PanelHeader title=move || t_string!(i18n, control_panel::title)>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </PanelHeader>
            <DetectionToggleButton
                status=status
                converting=converting
                on_start=start_detection
                on_stop=stop_detection
            />
            <div class="flex flex-col gap-2.5">
                <StatusSummary status=status />
            </div>
        </div>
    }
}
