//! Leptos UI components for the web frontend.

use leptos::prelude::*;

#[component]
pub(super) fn RangeControl(
    /// Accepts plain `&str` literals and reactive closures (translated labels
    /// are passed as `move || t_string!(...)` so they follow the locale).
    #[prop(into)]
    label: TextProp,
    min: u32,
    max: u32,
    value: ReadSignal<u32>,
    set_value: WriteSignal<u32>,
    on_push: Callback<u32>,
) -> impl IntoView {
    view! {
        <div class="flex items-center gap-2">
            <span class="ui-overlay-label w-16">{move || label.get()}</span>
            <input type="range" min=min.to_string() max=max.to_string() step="1" class="ui-range"
                prop:value={move || value.get().to_string()}
                on:change=move |ev| {
                    if let Ok(v)=event_target_value(&ev).parse::<u32>() {
                        let v=v.clamp(min,max);
                        set_value.set(v);
                        on_push.run(v);
                    }
                } />
            <span class="ui-overlay-value w-10 text-right">{move || value.get().to_string()}</span>
        </div>
    }
}
