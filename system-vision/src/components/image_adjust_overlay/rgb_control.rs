//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn RgbControl(
    rgb_red: ReadSignal<u16>,
    set_rgb_red: WriteSignal<u16>,
    rgb_green: ReadSignal<u16>,
    set_rgb_green: WriteSignal<u16>,
    rgb_blue: ReadSignal<u16>,
    set_rgb_blue: WriteSignal<u16>,
    on_push_rgb: Callback<(u16, u16, u16)>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="flex flex-col gap-1.5">
            <span class="ui-overlay-label">{t!(i18n, stream::rgb_levels)}</span>
            <div class="flex items-center gap-2">
                <span class="ui-rgb-label ui-rgb-label-r">"R"</span>
                <input type="range" min="0" max="255" step="1" class="ui-range"
                    prop:value={move || rgb_red.get().to_string()}
                    on:change=move |ev| {
                        if let Ok(v)=event_target_value(&ev).parse::<u16>() {
                            let v=v.min(255);
                            set_rgb_red.set(v);
                            on_push_rgb.run((v, rgb_green.get(), rgb_blue.get()));
                        }
                    } />
                <span class="ui-overlay-value w-8 text-right">{move || rgb_red.get().to_string()}</span>
            </div>
            <div class="flex items-center gap-2">
                <span class="ui-rgb-label ui-rgb-label-g">"G"</span>
                <input type="range" min="0" max="255" step="1" class="ui-range"
                    prop:value={move || rgb_green.get().to_string()}
                    on:change=move |ev| {
                        if let Ok(v)=event_target_value(&ev).parse::<u16>() {
                            let v=v.min(255);
                            set_rgb_green.set(v);
                            on_push_rgb.run((rgb_red.get(), v, rgb_blue.get()));
                        }
                    } />
                <span class="ui-overlay-value w-8 text-right">{move || rgb_green.get().to_string()}</span>
            </div>
            <div class="flex items-center gap-2">
                <span class="ui-rgb-label ui-rgb-label-b">"B"</span>
                <input type="range" min="0" max="255" step="1" class="ui-range"
                    prop:value={move || rgb_blue.get().to_string()}
                    on:change=move |ev| {
                        if let Ok(v)=event_target_value(&ev).parse::<u16>() {
                            let v=v.min(255);
                            set_rgb_blue.set(v);
                            on_push_rgb.run((rgb_red.get(), rgb_green.get(), v));
                        }
                    } />
                <span class="ui-overlay-value w-8 text-right">{move || rgb_blue.get().to_string()}</span>
            </div>
        </div>
    }
}
