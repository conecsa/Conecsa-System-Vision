//! A labeled range slider used by the stereo overlay alignment panel.

use leptos::prelude::*;

#[component]
pub(super) fn StereoRangeControl(
    /// Accepts plain `&str` literals and reactive closures (translated labels
    /// are passed as `move || t_string!(...)` so they follow the locale).
    #[prop(into)]
    label: TextProp,
    value: Signal<f32>,
    display: Signal<String>,
    min: i32,
    max: i32,
    on_change: Callback<f32>,
) -> impl IntoView {
    view! {
        <div class="flex items-center gap-2">
            <span class="ui-overlay-label w-16">{move || label.get()}</span>
            <input
                type="range" min=min.to_string() max=max.to_string() step="1"
                class="ui-range min-w-0"
                prop:value={move || value.get().round().to_string()}
                on:change=move |ev| {
                    if let Ok(p) = event_target_value(&ev).parse::<f32>() {
                        on_change.run(p);
                    }
                }
            />
            <span class="ui-overlay-value w-10 text-right">
                {display}
            </span>
        </div>
    }
}
