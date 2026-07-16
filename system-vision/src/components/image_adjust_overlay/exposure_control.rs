//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ExposureControl(
    auto_exposure: ReadSignal<bool>,
    set_auto_exposure: WriteSignal<bool>,
    exposure_time: ReadSignal<u32>,
    set_exposure_time: WriteSignal<u32>,
    exp_min: ReadSignal<u32>,
    exp_max: ReadSignal<u32>,
    on_push_exposure: Callback<(bool, u32)>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="flex flex-col gap-1.5">
            <span class="ui-overlay-label">{t!(i18n, stream::exposure)}</span>
            <div class="ui-segmented">
                <button type="button"
                    class=move || {
                        if !auto_exposure.get() { "ui-segmented-button ui-segmented-button-active" } else { "ui-segmented-button" }
                    }
                    on:click=move |_| {
                        set_auto_exposure.set(false);
                        on_push_exposure.run((false, exposure_time.get()));
                    }
                >{t!(i18n, stream::manual)}</button>
                <button type="button"
                    class=move || {
                        if auto_exposure.get() { "ui-segmented-button ui-segmented-button-active" } else { "ui-segmented-button" }
                    }
                    on:click=move |_| {
                        set_auto_exposure.set(true);
                        on_push_exposure.run((true, exposure_time.get()));
                    }
                >{t!(i18n, stream::auto)}</button>
            </div>
            {move || if !auto_exposure.get() {
                view! {
                    <input type="number" step="1"
                        prop:min={move || exp_min.get().to_string()}
                        prop:max={move || exp_max.get().to_string()}
                        class="ui-overlay-input"
                        prop:value={move || exposure_time.get().to_string()}
                        on:change=move |ev| {
                            if let Ok(v) = event_target_value(&ev).parse::<u32>() {
                                let v = v.clamp(exp_min.get(), exp_max.get());
                                set_exposure_time.set(v);
                                on_push_exposure.run((false, v));
                            }
                        }
                    />
                }.into_any()
            } else {
                view! { <></> }.into_any()
            }}
        </div>
    }
}
