//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn TriggerToggleRow(
    gpio_enabled: ReadSignal<bool>,
    loading: ReadSignal<bool>,
    on_toggle: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="ui-row">
            <div class="flex flex-col gap-0.5">
                <span class="ui-label">{t!(i18n, settings::trigger_via_gpio)}</span>
                <span class="ui-help">
                    {t!(i18n, settings::trigger_help)}
                </span>
            </div>
            <button
                class={move || {
                    if gpio_enabled.get() {
                        "ui-toggle ui-toggle-on"
                    } else {
                        "ui-toggle ui-toggle-off"
                    }
                }}
                on:click=move |_| on_toggle.run(())
                disabled=move || loading.get()
                title={move || if gpio_enabled.get() {
                    t_string!(i18n, settings::disable_gpio_trigger)
                } else {
                    t_string!(i18n, settings::enable_gpio_trigger)
                }}
            >
                <span class={move || {
                    if gpio_enabled.get() {
                        "ui-toggle-knob ui-toggle-knob-on"
                    } else {
                        "ui-toggle-knob"
                    }
                }} />
            </button>
        </div>
    }
}
