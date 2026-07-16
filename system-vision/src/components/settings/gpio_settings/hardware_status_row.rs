//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn HardwareStatusRow(gpio_available: ReadSignal<bool>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="ui-row">
            <span class="ui-label">{t!(i18n, settings::hardware_gpio)}</span>
            <span class={move || {
                if gpio_available.get() {
                    "ui-badge ui-badge-success"
                } else {
                    "ui-badge ui-badge-danger"
                }
            }}>
                {move || if gpio_available.get() {
                    t_string!(i18n, settings::available)
                } else {
                    t_string!(i18n, settings::unavailable)
                }}
            </span>
        </div>
    }
}
