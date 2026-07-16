//! Leptos UI components for the web frontend.

use super::ip_config_form::IpConfigForm;
use super::wifi_network_row::WifiNetworkRow;
use crate::api;
use crate::api::{InterfaceConfig, WifiNetwork, WifiStatus};
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

#[derive(Clone, Copy)]
pub(super) struct WifiPanelState {
    scanning: RwSignal<bool>,
    networks: RwSignal<Vec<WifiNetwork>>,
    selected_ssid: RwSignal<String>,
    wifi_password: RwSignal<String>,
    connecting: RwSignal<bool>,
}

impl WifiPanelState {
    pub(super) fn new() -> Self {
        Self {
            scanning: RwSignal::new(false),
            networks: RwSignal::new(Vec::<WifiNetwork>::new()),
            selected_ssid: RwSignal::new(String::new()),
            wifi_password: RwSignal::new(String::new()),
            connecting: RwSignal::new(false),
        }
    }
}

/// Handle wifi action response.
fn handle_wifi_action_response(
    success: bool,
    message: String,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
    on_success: impl FnOnce(),
) {
    if success {
        set_success_msg.set(message);
        on_success();
    } else {
        set_error_msg.set(message);
    }
}

#[component]
pub(super) fn WifiNetworkPanel(
    wifi: InterfaceConfig,
    wifi_status: WifiStatus,
    state: WifiPanelState,
    on_config_changed: Callback<()>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let scanning = state.scanning;
    let networks = state.networks;
    let selected_ssid = state.selected_ssid;
    let wifi_password = state.wifi_password;
    let connecting = state.connecting;

    let do_scan = move |_| {
        let locale = i18n.get_locale_untracked();
        scanning.set(true);
        spawn_local(async move {
            match api::scan_wifi().await {
                Ok(resp) => networks.set(resp.networks),
                Err(e) => {
                    set_error_msg.set(td_string!(locale, settings::wifi_scan_failed, err = e))
                }
            }
            scanning.set(false);
        });
    };

    let do_connect = move |_| {
        let ssid = selected_ssid.get_untracked();
        if ssid.is_empty() {
            return;
        }
        let password = wifi_password.get_untracked();
        let locale = i18n.get_locale_untracked();
        connecting.set(true);
        spawn_local(async move {
            match api::connect_wifi(ssid.clone(), password).await {
                Ok(resp) => handle_wifi_action_response(
                    resp.success,
                    resp.message,
                    set_error_msg,
                    set_success_msg,
                    || {
                        wifi_password.set(String::new());
                        on_config_changed.run(());
                    },
                ),
                Err(e) => {
                    set_error_msg.set(td_string!(locale, settings::failed_to_connect, err = e))
                }
            }
            connecting.set(false);
        });
    };

    let do_forget = move |_| {
        let ssid = selected_ssid.get_untracked();
        if ssid.is_empty() {
            return;
        }
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::forget_wifi(ssid.clone()).await {
                Ok(resp) => handle_wifi_action_response(
                    resp.success,
                    resp.message,
                    set_error_msg,
                    set_success_msg,
                    || {
                        selected_ssid.set(String::new());
                        on_config_changed.run(());
                    },
                ),
                Err(e) => set_error_msg
                    .set(td_string!(locale, settings::failed_to_forget_network, err = e)),
            }
        });
    };

    let selected_secured = move || {
        let ssid = selected_ssid.get();
        networks
            .get()
            .iter()
            .find(|n| n.ssid == ssid)
            .map(|n| n.security.to_uppercase() != "OPEN")
            .unwrap_or(true)
    };
    let selected_saved = move || {
        let ssid = selected_ssid.get();
        networks
            .get()
            .iter()
            .find(|n| n.ssid == ssid)
            .map(|n| n.saved)
            .unwrap_or(false)
    };
    let ws_ssid = wifi_status.ssid.clone();
    let ws_state = wifi_status.state.clone();
    let connected_label = move || {
        if ws_ssid.is_empty() {
            t_string!(i18n, settings::not_connected).to_string()
        } else {
            format!("{} ({})", ws_ssid, ws_state)
        }
    };

    view! {
        <div class="flex flex-col gap-3">
            <div class="ui-row ui-row-wrap">
                <span class="ui-label-xs">{t!(i18n, settings::connected)}</span>
                <span class="ui-value min-w-0 break-all text-xs font-mono">
                    {connected_label}
                </span>
            </div>

            <button
                class="ui-button ui-button-neutral ui-button-xs w-full"
                disabled=move || scanning.get()
                on:click=do_scan
            >
                {move || if scanning.get() {
                    t_string!(i18n, settings::scanning)
                } else {
                    t_string!(i18n, settings::scan_for_networks)
                }}
            </button>

            <div class="flex flex-col gap-1 max-h-48 overflow-y-auto">
                {move || {
                    networks
                        .get()
                        .into_iter()
                        .map(|network| {
                            view! {
                                <WifiNetworkRow
                                    network=network
                                    selected_ssid=selected_ssid
                                    wifi_password=wifi_password
                                />
                            }
                        })
                        .collect_view()
                }}
            </div>

            {move || {
                if selected_ssid.get().is_empty() {
                    return view! { <div /> }.into_any();
                }
                view! {
                    <div class="ui-section-rule-sm flex flex-col gap-2">
                        {move || {
                            if selected_secured() {
                                view! {
                                    <input
                                        type="password"
                                        class="ui-input ui-input-sm"
                                        placeholder=move || if selected_saved() {
                                            t_string!(i18n, settings::saved_leave_blank)
                                        } else {
                                            t_string!(i18n, settings::password)
                                        }
                                        prop:value=move || wifi_password.get()
                                        on:input=move |e| wifi_password.set(event_target_value(&e))
                                    />
                                }
                                .into_any()
                            } else {
                                view! { <div /> }.into_any()
                            }
                        }}
                        <div class="flex gap-2">
                            <button
                                class="ui-button ui-button-primary ui-button-xs flex-1"
                                disabled=move || connecting.get()
                                on:click=do_connect
                            >
                                {move || if connecting.get() {
                                    t_string!(i18n, settings::connecting)
                                } else {
                                    t_string!(i18n, settings::connect)
                                }}
                            </button>
                            {move || {
                                selected_saved().then(|| view! {
                                    <button
                                        class="ui-button ui-button-neutral ui-button-xs"
                                        on:click=do_forget
                                    >
                                        {t!(i18n, settings::forget)}
                                    </button>
                                })
                            }}
                        </div>
                    </div>
                }
                .into_any()
            }}

            {(wifi.present).then(|| view! {
                <div class="ui-section-rule-sm">
                    <IpConfigForm
                        interface="wifi"
                        initial=wifi.clone()
                        on_config_changed=on_config_changed
                        set_error_msg=set_error_msg
                        set_success_msg=set_success_msg
                    />
                </div>
            })}
        </div>
    }
}
