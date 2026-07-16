//! Leptos UI components for the web frontend.

use crate::api;
use crate::api::InterfaceConfig;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

/// DHCP/static IPv4 form for one interface ("wired" | "wifi").
#[component]
pub(super) fn IpConfigForm(
    interface: &'static str,
    initial: InterfaceConfig,
    on_config_changed: Callback<()>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let current_cidr = match (&initial.address, initial.prefix) {
        (Some(addr), Some(pfx)) => format!("{}/{}", addr, pfx),
        (Some(addr), None) => addr.clone(),
        _ => "(DHCP)".to_string(),
    };

    let (form_method, set_form_method) = signal(initial.method.clone());
    let (form_address, set_form_address) = signal(initial.address.clone().unwrap_or_default());
    let (form_prefix, set_form_prefix) = signal(
        initial
            .prefix
            .map(|p| p.to_string())
            .unwrap_or_else(|| "24".to_string()),
    );
    let (form_gateway, set_form_gateway) = signal(initial.gateway.clone().unwrap_or_default());
    let (form_dns1, set_form_dns1) = signal(initial.dns.first().cloned().unwrap_or_default());
    let (form_dns2, set_form_dns2) = signal(initial.dns.get(1).cloned().unwrap_or_default());
    let (applying, set_applying) = signal(false);

    let radio_name = format!("net_method_{interface}");

    let apply = move |_| {
        let locale = i18n.get_locale_untracked();
        let method = form_method.get_untracked();
        let address = form_address.get_untracked();
        let prefix_str = form_prefix.get_untracked();
        let gateway = form_gateway.get_untracked();
        let dns1 = form_dns1.get_untracked();
        let dns2 = form_dns2.get_untracked();

        if method == "static" && address.is_empty() {
            set_error_msg
                .set(td_string!(locale, settings::ip_required_for_static).to_string());
            return;
        }

        let prefix: Option<u8> = prefix_str.parse().ok();
        let addr = if method == "static" && !address.is_empty() {
            Some(address)
        } else {
            None
        };
        let gw = if !gateway.is_empty() {
            Some(gateway)
        } else {
            None
        };
        let dns: Vec<String> = [dns1, dns2].into_iter().filter(|s| !s.is_empty()).collect();

        set_applying.set(true);
        spawn_local(async move {
            match api::set_network_config(interface.to_string(), method, addr, prefix, gw, dns)
                .await
            {
                Ok(resp) => {
                    if resp.success {
                        set_success_msg.set(resp.message);
                        on_config_changed.run(());
                    } else {
                        set_error_msg.set(resp.message);
                    }
                }
                Err(e) => set_error_msg
                    .set(td_string!(locale, settings::failed_to_apply_config, err = e)),
            }
            set_applying.set(false);
        });
    };

    view! {
        <div class="flex flex-col gap-3">
            <div class="ui-row ui-row-wrap">
                <span class="ui-label-xs">{t!(i18n, settings::current_ip)}</span>
                <span class="ui-value min-w-0 break-all text-xs font-mono">
                    {current_cidr}
                </span>
            </div>

            <div class="grid grid-cols-2 gap-2">
                <label class="ui-radio-label">
                    <input
                        type="radio"
                        name=radio_name.clone()
                        class="ui-radio"
                        checked=move || form_method.get() == "auto"
                        on:change=move |_| set_form_method.set("auto".to_string())
                    />
                    {t!(i18n, settings::dhcp_automatic)}
                </label>
                <label class="ui-radio-label">
                    <input
                        type="radio"
                        name=radio_name
                        class="ui-radio"
                        checked=move || form_method.get() == "static"
                        on:change=move |_| set_form_method.set("static".to_string())
                    />
                    {t!(i18n, settings::static_ip)}
                </label>
            </div>

            {move || {
                if form_method.get() == "static" {
                    view! {
                        <div class="flex flex-col gap-2.5">
                            <div class="grid grid-cols-[minmax(0,1fr)_5rem] gap-2">
                                <div>
                                    <label class="ui-label-xs block mb-1">{t!(i18n, settings::ip_address)}</label>
                                    <input
                                        type="text"
                                        class="ui-input ui-input-sm ui-input-mono"
                                        placeholder="192.168.1.100"
                                        prop:value=form_address
                                        on:input=move |e| set_form_address.set(event_target_value(&e))
                                    />
                                </div>
                                <div>
                                    <label class="ui-label-xs block mb-1">{t!(i18n, settings::prefix)}</label>
                                    <input
                                        type="number"
                                        min="1"
                                        max="32"
                                        class="ui-input ui-input-sm ui-input-mono"
                                        placeholder="24"
                                        prop:value=form_prefix
                                        on:input=move |e| set_form_prefix.set(event_target_value(&e))
                                    />
                                </div>
                            </div>
                            <div>
                                <label class="ui-label-xs block mb-1">{t!(i18n, settings::gateway)}</label>
                                <input
                                    type="text"
                                    class="ui-input ui-input-sm ui-input-mono"
                                    placeholder="192.168.1.1"
                                    prop:value=form_gateway
                                    on:input=move |e| set_form_gateway.set(event_target_value(&e))
                                />
                            </div>
                            <div class="grid grid-cols-2 gap-2">
                                <div>
                                    <label class="ui-label-xs block mb-1">"DNS 1"</label>
                                    <input
                                        type="text"
                                        class="ui-input ui-input-sm ui-input-mono"
                                        placeholder="8.8.8.8"
                                        prop:value=form_dns1
                                        on:input=move |e| set_form_dns1.set(event_target_value(&e))
                                    />
                                </div>
                                <div>
                                    <label class="ui-label-xs block mb-1">"DNS 2"</label>
                                    <input
                                        type="text"
                                        class="ui-input ui-input-sm ui-input-mono"
                                        placeholder="8.8.4.4"
                                        prop:value=form_dns2
                                        on:input=move |e| set_form_dns2.set(event_target_value(&e))
                                    />
                                </div>
                            </div>
                        </div>
                    }
                    .into_any()
                } else {
                    view! { <div /> }.into_any()
                }
            }}

            <button
                class="ui-button ui-button-primary ui-button-xs w-full"
                disabled=move || applying.get()
                on:click=apply
            >
                {move || if applying.get() {
                    t_string!(i18n, settings::applying)
                } else {
                    t_string!(i18n, settings::apply_configuration)
                }}
            </button>
        </div>
    }
}
