//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::LabelBox;
use crate::components::configuration::threshold_slider::ThresholdSlider;
use crate::i18n::*;

/// AI-assist (SAM) prompt bar: a concept text prompt + Suggest/Accept/Clear and
/// the confidence threshold. Rendered by the editor only while SAM is on.
/// Suggestions are tagged with the prompt's class (created if new) on Accept.
#[component]
pub(super) fn LabelSamPanel(
    sam_text: ReadSignal<String>,
    set_sam_text: WriteSignal<String>,
    sam_busy: ReadSignal<bool>,
    sam_suggestions: ReadSignal<Vec<LabelBox>>,
    sam_threshold: ReadSignal<f32>,
    set_sam_threshold: WriteSignal<f32>,
    on_sam_suggest: Callback<()>,
    on_sam_accept: Callback<()>,
    on_sam_clear: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="ui-list-box flex flex-col gap-2 p-2">
            <div class="flex items-center gap-2 flex-wrap">
                <input
                    type="text"
                    class="ui-input ui-input-sm flex-1 min-w-32"
                    placeholder=move || t_string!(i18n, training::describe_object_placeholder)
                    prop:value=move || sam_text.get()
                    on:input=move |ev| set_sam_text.set(event_target_value(&ev))
                />
                <button
                    class="ui-button ui-button-primary ui-button-xs"
                    disabled=move || sam_busy.get()
                    on:click=move |_| on_sam_suggest.run(())
                >
                    {move || if sam_busy.get() {
                        t_string!(i18n, training::segmenting)
                    } else {
                        t_string!(i18n, training::suggest)
                    }}
                </button>
                {move || if !sam_suggestions.get().is_empty() {
                    let n = sam_suggestions.get().len();
                    let prompt = sam_text.get().trim().to_string();
                    let label = if prompt.is_empty() {
                        t_string!(i18n, training::accept_as_active_class, count = n)
                    } else {
                        t_string!(i18n, training::accept_as_class, count = n, name = prompt)
                    };
                    view! {
                        <button
                            class="ui-button ui-button-success ui-button-xs"
                            on:click=move |_| on_sam_accept.run(())
                            title=t_string!(i18n, training::accept_suggestions_title)
                        >
                            {label}
                        </button>
                    }.into_any()
                } else {
                    view! { <span/> }.into_any()
                }}
                <button
                    class="ui-button ui-button-neutral ui-button-xs"
                    on:click=move |_| on_sam_clear.run(())
                >
                    {t!(i18n, training::clear)}
                </button>
            </div>
            // Confidence threshold for SAM suggestions — reuses the dashboard's
            // slider; re-runs Suggest on change.
            <ThresholdSlider
                label=move || t_string!(i18n, training::ai_confidence)
                description=move || t_string!(i18n, training::ai_confidence_desc)
                value=sam_threshold
                set_value=set_sam_threshold
                on_change=Callback::new(move |_: f32| on_sam_suggest.run(()))
            />
        </div>
    }
}
