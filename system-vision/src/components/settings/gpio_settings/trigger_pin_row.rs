//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn TriggerPinRow(
    gpio_enabled: ReadSignal<bool>,
    trigger_state: ReadSignal<Option<bool>>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || {
            if gpio_enabled.get() {
                view! {
                    <div class="ui-row">
                        <span class="ui-label">{t!(i18n, settings::trigger_pin_label)}</span>
                        <span class={move || {
                            match trigger_state.get() {
                                Some(true)  => "ui-badge ui-badge-success",
                                Some(false) => "ui-badge ui-badge-warning",
                                None        => "ui-badge ui-badge-muted",
                            }
                        }}>
                            {move || match trigger_state.get() {
                                Some(true)  => t_string!(i18n, settings::trigger_high_processing),
                                Some(false) => t_string!(i18n, settings::trigger_low_frozen),
                                None        => "—",
                            }}
                        </span>
                    </div>
                }.into_any()
            } else {
                view! { <div class="hidden" /> }.into_any()
            }
        }}
    }
}
