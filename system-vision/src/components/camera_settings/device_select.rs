//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn CaptureDeviceSelect(
    devices: ReadSignal<Vec<(u32, String)>>,
    selected_index: ReadSignal<u32>,
    set_selected_index: WriteSignal<u32>,
) -> impl IntoView {
    let i18n = use_i18n();

    view! {
        <div class="flex flex-col gap-1.5">
            <label class="ui-label">
                {t!(i18n, camera::capture_device)}
            </label>
            {move || {
                let devs = devices.get();
                let current = selected_index.get();
                if devs.is_empty() {
                    view! {
                        <div class="ui-alert-warning px-3 py-2.5 text-sm">
                            {t_string!(i18n, camera::no_devices_hint)}" "
                            <code class="font-mono text-xs">"--device /dev/video0"</code>"."
                        </div>
                    }.into_any()
                } else {
                    view! {
                        <select
                            class="ui-select cursor-pointer"
                            on:change=move |ev| {
                                if let Ok(v) = event_target_value(&ev).parse::<u32>() {
                                    set_selected_index.set(v);
                                }
                            }
                        >
                            {devs.iter().map(|(idx, label)| {
                                let is_selected = *idx == current;
                                let idx_val = idx.to_string();
                                let label_clone = label.clone();
                                view! {
                                    <option value={idx_val} selected={is_selected}>
                                        {label_clone}
                                    </option>
                                }
                            }).collect::<Vec<_>>()}
                        </select>
                    }.into_any()
                }
            }}
        </div>
    }
}
