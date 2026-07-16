//! Leptos UI components for the web frontend.

use leptos::prelude::*;

/// The `ThresholdSlider` view component.
#[component]
pub fn ThresholdSlider(
    /// Accepts plain `&str` literals and reactive closures (translated labels
    /// are passed as `move || t_string!(...)` so they follow the locale).
    #[prop(into)]
    label: TextProp,
    /// Same contract as `label`.
    #[prop(into)]
    description: TextProp,
    value: ReadSignal<f32>,
    set_value: WriteSignal<f32>,
    on_change: Callback<f32>,
) -> impl IntoView {
    let on_input = move |ev| {
        if let Ok(val) = event_target_value(&ev).parse::<f32>() {
            set_value.set(val);
        }
    };

    let on_commit = move |ev| {
        if let Ok(val) = event_target_value(&ev).parse::<f32>() {
            on_change.run(val);
        }
    };

    view! {
        <div class="mb-4">
            <h3 class="ui-section-title mb-2">{move || label.get()}</h3>
            <div class="flex items-center gap-3 mb-2">
                <input
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.01"
                    prop:value={move || value.get().to_string()}
                    on:input=on_input
                    on:change=on_commit
                    class="ui-range"
                />
                <span class="ui-value min-w-12 text-center text-sm">
                    {move || format!("{:.2}", value.get())}
                </span>
            </div>
            <p class="ui-help text-sm leading-relaxed">
                {move || description.get()}
            </p>
        </div>
    }
}
