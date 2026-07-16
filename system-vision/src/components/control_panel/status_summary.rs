//! Leptos UI components for the web frontend.

use crate::app::SystemStatus;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn StatusSummary(status: ReadSignal<Option<SystemStatus>>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <>
            <div class="ui-row">
                <span class="ui-label">{t!(i18n, control_panel::status)}</span>
                <span class={move || {
                    if status.get().map(|s| s.is_running).unwrap_or(false) {
                        "ui-badge ui-badge-success"
                    } else {
                        "ui-badge ui-badge-muted"
                    }
                }}>
                    {move || if status.get().map(|s| s.is_running).unwrap_or(false) {
                        t_string!(i18n, control_panel::running)
                    } else {
                        t_string!(i18n, control_panel::stopped)
                    }}
                </span>
            </div>
            <div class="ui-row">
                <span class="ui-label shrink-0">{t!(i18n, control_panel::model)}</span>
                <span class="ui-value min-w-0 text-right text-sm wrap-break-word">
                    {move || status.get().map(|s| s.model).unwrap_or_default()}
                </span>
            </div>
            <div class="ui-row">
                <span class="ui-label">{t!(i18n, control_panel::hardware_acceleration)}</span>
                <span class="ui-value shrink-0 text-right text-sm">
                    {move || {
                        status.get()
                            .map(|s| {
                                match s.acceleration_type.as_str() {
                                    "GPU" => "GPU".to_string(),
                                    "CPU" => "CPU".to_string(),
                                    "Disabled" | "None" | "" => {
                                        t_string!(i18n, control_panel::disabled).to_string()
                                    }
                                    other => other.to_string()
                                }
                            })
                            .unwrap_or_else(|| t_string!(i18n, control_panel::disabled).to_string())
                    }}
                </span>
            </div>
        </>
    }
}
