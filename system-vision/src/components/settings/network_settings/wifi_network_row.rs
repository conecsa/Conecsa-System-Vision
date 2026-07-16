//! Leptos UI components for the web frontend.

use crate::api::WifiNetwork;
use leptos::prelude::*;

#[component]
pub(super) fn WifiNetworkRow(
    network: WifiNetwork,
    selected_ssid: RwSignal<String>,
    wifi_password: RwSignal<String>,
) -> impl IntoView {
    let ssid = network.ssid.clone();
    let ssid_click = ssid.clone();
    let is_selected = move || selected_ssid.get() == ssid;
    let row_class = move || {
        let base = "ui-row ui-row-sm ui-row-clickable";
        if is_selected() {
            format!("{base} ui-row-selected")
        } else {
            base.to_string()
        }
    };
    let secured = network.security.to_uppercase() != "OPEN";

    view! {
        <div
            class=row_class
            on:click=move |_| {
                selected_ssid.set(ssid_click.clone());
                wifi_password.set(String::new());
            }
        >
            <span class="flex items-center gap-1.5 min-w-0">
                {(network.in_use).then(|| view! {
                    <svg class="w-3.5 h-3.5 shrink-0 stroke-current ui-accent" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                })}
                <span class="ui-value truncate font-mono">
                    {network.ssid.clone()}
                </span>
                {secured.then(|| view! {
                    <svg class="w-3.5 h-3.5 shrink-0 stroke-current ui-icon-muted" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                            d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 0h10.5a2.25 2.25 0 012.25 2.25v6.75a2.25 2.25 0 01-2.25 2.25H6.75a2.25 2.25 0 01-2.25-2.25v-6.75a2.25 2.25 0 012.25-2.25z" />
                    </svg>
                })}
            </span>
            <span class="ui-muted shrink-0 text-[11px] font-mono">
                {format!("{} dBm", network.signal)}
            </span>
        </div>
    }
}
