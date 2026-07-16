//! Leptos UI components for the web frontend.

use crate::components::{GpioSettings, NetworkSettings};
use leptos::prelude::*;

/// The `Settings` view component.
#[component]
pub fn Settings(
    refresh_network: ReadSignal<u32>,
    refresh_gpio: ReadSignal<u32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    view! {
        <div class="min-h-full grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
            <GpioSettings
                refresh_gpio=refresh_gpio
                set_error_msg=set_error_msg
                set_success_msg=set_success_msg
            />
            <NetworkSettings
                refresh_network=refresh_network
                set_error_msg=set_error_msg
                set_success_msg=set_success_msg
            />
        </div>
    }
}
