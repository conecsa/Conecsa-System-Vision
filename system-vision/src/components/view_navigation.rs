//! Leptos UI components for the web frontend.

use crate::components::control_panel::{NavButton, ViewMode};
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub fn ViewNavigation(
    current_view: ReadSignal<ViewMode>,
    set_current_view: WriteSignal<ViewMode>,
    /// Entering the training view stops inference, so the button asks for
    /// confirmation (owned by MainView) instead of switching the view directly.
    on_training_request: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Role gating (hub-provided): common users keep the live stream but the
    // other views are disabled, not hidden.
    let privileged = crate::components::access::privileged();
    view! {
        <div class="ui-card ui-card-pad flex flex-col">
            <PanelHeader title=move || t_string!(i18n, main::navigation)>
                <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" stroke-width="2" />
                <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" stroke-width="2" />
                <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" stroke-width="2" />
                <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" stroke-width="2" />
            </PanelHeader>
            <div class="flex justify-around items-center gap-2">
                <NavButton
                    view_mode=ViewMode::LiveStream
                    current_view=current_view
                    set_current_view=set_current_view
                    title=move || t_string!(i18n, main::live_stream_title)
                    label=move || t_string!(i18n, main::stream_label)
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </NavButton>

                <NavButton
                    view_mode=ViewMode::CameraSettings
                    current_view=current_view
                    set_current_view=set_current_view
                    title=move || if privileged {
                        t_string!(i18n, main::camera_settings_title)
                    } else {
                        t_string!(i18n, common::restricted_to_admins)
                    }
                    label=move || t_string!(i18n, main::camera_label)
                    disabled=!privileged
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </NavButton>

                <NavButton
                    view_mode=ViewMode::Flow
                    current_view=current_view
                    set_current_view=set_current_view
                    title=move || if privileged {
                        t_string!(i18n, main::flow_editor_title)
                    } else {
                        t_string!(i18n, common::restricted_to_admins)
                    }
                    label=move || t_string!(i18n, main::flow_label)
                    disabled=!privileged
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </NavButton>

                <NavButton
                    view_mode=ViewMode::Settings
                    current_view=current_view
                    set_current_view=set_current_view
                    title=move || if privileged {
                        t_string!(i18n, main::gpio_settings_title)
                    } else {
                        t_string!(i18n, common::restricted_to_admins)
                    }
                    label=move || t_string!(i18n, main::settings_label)
                    disabled=!privileged
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </NavButton>

                <button
                    class={move || {
                        if current_view.get() == ViewMode::Training {
                            "nav-button nav-button-active disabled:opacity-50 disabled:cursor-not-allowed"
                        } else {
                            "nav-button disabled:opacity-50 disabled:cursor-not-allowed"
                        }
                    }}
                    disabled=!privileged
                    on:click=move |_| on_training_request.run(())
                    title=move || if privileged {
                        t_string!(i18n, main::model_training_title)
                    } else {
                        t_string!(i18n, common::restricted_to_admins)
                    }
                >
                    <svg class="nav-button-icon stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
                    </svg>
                    <span class="nav-button-label">{t!(i18n, main::training_label)}</span>
                </button>
            </div>
        </div>
    }
}
