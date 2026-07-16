//! Leptos UI components for the web frontend.

use crate::app::get_node_red_url;
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;

/// The `Flow` view component.
#[component]
pub fn Flow() -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="app-panel app-flow-panel">
            <div class="app-flow-header">
                <PanelHeader
                    title=move || t_string!(i18n, flow::flow_editor)
                    margin_bottom=false
                    trailing=view! {
                        <span class="ui-help">"Node-RED"</span>
                    }.into_any()
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </PanelHeader>
            </div>
            <iframe
                src=get_node_red_url()
                class="app-flow-frame"
                allow="same-origin"
                title=move || t_string!(i18n, flow::node_red_frame_title)
            />
        </div>
    }
}
