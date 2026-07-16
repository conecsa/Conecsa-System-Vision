//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn NetworkSettingsTabs(
    active_tab: ReadSignal<String>,
    set_active_tab: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let tab_class = move |tab: &str| {
        if active_tab.get() == tab {
            "ui-tab ui-tab-active"
        } else {
            "ui-tab"
        }
    };

    view! {
        <div role="tablist" class="ui-tabs mb-3">
            <button
                type="button"
                role="tab"
                aria-selected=move || active_tab.get() == "wired"
                class=move || tab_class("wired")
                on:click=move |_| set_active_tab.set("wired".to_string())
            >
                {t!(i18n, settings::wired_tab)}
            </button>
            <button
                type="button"
                role="tab"
                aria-selected=move || active_tab.get() == "wifi"
                class=move || tab_class("wifi")
                on:click=move |_| set_active_tab.set("wifi".to_string())
            >
                "Wi-Fi"
            </button>
        </div>
    }
}
