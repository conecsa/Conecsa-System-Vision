//! Leptos UI components for the web frontend.

use crate::api;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::hardware_status_row::HardwareStatusRow;
use super::pin_map::PinMap;
use super::trigger_pin_row::TriggerPinRow;
use super::trigger_toggle_row::TriggerToggleRow;

/// The `GpioSettings` view component.
#[component]
pub fn GpioSettings(
    refresh_gpio: ReadSignal<u32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();

    // Local state: enabled or not, availability, trigger status
    let (gpio_enabled, set_gpio_enabled) = signal(false);
    let (gpio_available, set_gpio_available) = signal(false);
    let (trigger_state, set_trigger_state) = signal(Option::<bool>::None);
    let (loading, set_loading) = signal(false);

    // Load current state on mount
    let fetch_status = move || {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::get_gpio_status().await {
                Ok(status) => {
                    set_gpio_enabled.set(status.gpio_enabled);
                    set_gpio_available.set(status.gpio_available);
                    set_trigger_state.set(status.trigger_state);
                }
                Err(e) => {
                    set_error_msg
                        .set(td_string!(locale, settings::failed_to_get_gpio_status, err = e));
                }
            }
        });
    };

    // Load on initialization and whenever an app event invalidates GPIO state.
    Effect::new(move |_| {
        let _ = refresh_gpio.get();
        fetch_status();
    });

    // Auto-refresh every 1s while the component is visible
    Effect::new(move |_| {
        spawn_local(async move {
            loop {
                gloo_timers::future::TimeoutFuture::new(1000).await;
                if let Ok(status) = api::get_gpio_status().await {
                    set_gpio_enabled.set(status.gpio_enabled);
                    set_gpio_available.set(status.gpio_available);
                    set_trigger_state.set(status.trigger_state);
                }
            }
        });
    });

    let toggle_gpio = Callback::new(move |_| {
        let new_state = !gpio_enabled.get();
        let locale = i18n.get_locale_untracked();
        set_loading.set(true);
        spawn_local(async move {
            match api::set_gpio_trigger(new_state).await {
                Ok(resp) => {
                    set_gpio_enabled.set(resp.gpio_enabled);
                    set_success_msg.set(resp.message);
                }
                Err(e) => {
                    set_error_msg
                        .set(td_string!(locale, settings::error_configuring_gpio, err = e));
                }
            }
            set_loading.set(false);
        });
    });

    view! {
        <div class="ui-card ui-card-pad">
            <h2 class="ui-section-header ui-section-header-lg">
                <svg class="w-5 h-5 stroke-current ui-icon-muted" viewBox="0 0 24 24" fill="none">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {t!(i18n, settings::gpio_settings_title)}
            </h2>

            <div class="flex flex-col gap-4">
                <HardwareStatusRow gpio_available=gpio_available />
                <TriggerToggleRow
                    gpio_enabled=gpio_enabled
                    loading=loading
                    on_toggle=toggle_gpio
                />
                <TriggerPinRow gpio_enabled=gpio_enabled trigger_state=trigger_state />
                <PinMap />
            </div>
        </div>
    }
}
