//! Leptos UI components for the web frontend.

use super::ip_config_form::IpConfigForm;
use crate::api::InterfaceConfig;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn WiredNetworkPanel(
    wired: InterfaceConfig,
    on_config_changed: Callback<()>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    if !wired.present {
        return view! {
            <div class="ui-help">
                {t!(i18n, settings::no_wired_interface)}
            </div>
        }
        .into_any();
    }

    view! {
        <IpConfigForm
            interface="wired"
            initial=wired
            on_config_changed=on_config_changed
            set_error_msg=set_error_msg
            set_success_msg=set_success_msg
        />
    }
    .into_any()
}
