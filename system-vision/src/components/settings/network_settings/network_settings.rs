//! Leptos UI components for the web frontend.

use crate::api;
use crate::api::NetworkConfig;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::tabs::NetworkSettingsTabs;
use super::wifi_panel::{WifiNetworkPanel, WifiPanelState};
use super::wired_panel::WiredNetworkPanel;

/// Network Settings card - wired + Wi-Fi, on a single card with two tabs.
#[component]
pub fn NetworkSettings(
    refresh_network: ReadSignal<u32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (loading, set_loading) = signal(true);
    let config = RwSignal::new(None::<NetworkConfig>);
    let (active_tab, set_active_tab) = signal("wired".to_string());
    let wifi_state = WifiPanelState::new();

    let reload_config = move || {
        let locale = i18n.get_locale_untracked();
        set_loading.set(true);
        spawn_local(async move {
            match api::get_network_config().await {
                Ok(cfg) => config.set(Some(cfg)),
                Err(e) => set_error_msg
                    .set(td_string!(locale, settings::failed_to_load_network_config, err = e)),
            }
            set_loading.set(false);
        });
    };

    Effect::new(move |_| {
        let _ = refresh_network.get();
        reload_config();
    });

    let on_config_changed = Callback::new(move |_| reload_config());

    view! {
        <div class="ui-card ui-card-pad-sm">
            <h2 class="ui-section-header ui-section-header-sm">
                <svg class="w-5 h-5 stroke-current ui-icon-muted" viewBox="0 0 24 24" fill="none">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z" />
                </svg>
                {t!(i18n, settings::network_settings_title)}
            </h2>

            <NetworkSettingsTabs active_tab=active_tab set_active_tab=set_active_tab />

            {move || {
                if loading.get() {
                    return view! {
                        <div class="text-sm ui-muted">{t!(i18n, common::loading)}</div>
                    }
                        .into_any();
                }
                let Some(cfg) = config.get() else {
                    return view! { <div /> }.into_any();
                };

                if active_tab.get() == "wired" {
                    view! {
                        <WiredNetworkPanel
                            wired=cfg.wired.clone()
                            on_config_changed=on_config_changed
                            set_error_msg=set_error_msg
                            set_success_msg=set_success_msg
                        />
                    }
                        .into_any()
                } else {
                    view! {
                        <WifiNetworkPanel
                            wifi=cfg.wifi.clone()
                            wifi_status=cfg.wifi_status.clone()
                            state=wifi_state
                            on_config_changed=on_config_changed
                            set_error_msg=set_error_msg
                            set_success_msg=set_success_msg
                        />
                    }
                        .into_any()
                }
            }}
        </div>
    }
}
