//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::i18n::*;

/// Asks how many copies to make of a labeled image. Mirrors the epochs prompt
/// in `TrainModal`. The editor owns the count/busy state and the API call;
/// this only renders + emits `on_confirm`.
#[component]
pub(super) fn ReplicateModal(
    visible: ReadSignal<bool>,
    set_visible: WriteSignal<bool>,
    count: ReadSignal<u32>,
    set_count: WriteSignal<u32>,
    busy: ReadSignal<bool>,
    on_confirm: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if visible.get() {
            view! {
                <div class="ui-modal-backdrop">
                    <div class="ui-card ui-card-pad ui-modal ui-modal-sm">
                        <h3 class="ui-card-title mb-4">
                            {t_string!(i18n, training::replicate_image)}
                        </h3>

                        <label class="ui-label-xs block mb-1">
                            {t_string!(i18n, training::number_of_replicas)}
                        </label>
                        <input
                            type="number"
                            min="1" max="50"
                            class="ui-input mb-1"
                            prop:value=move || count.get().to_string()
                            on:input=move |ev| {
                                if let Ok(v) = event_target_value(&ev).parse::<u32>() {
                                    set_count.set(v.clamp(1, 50));
                                }
                            }
                        />
                        <p class="ui-help-xs mb-6">
                            {t_string!(i18n, training::replicate_help)}
                        </p>

                        <div class="flex justify-end gap-2">
                            <button
                                class="ui-button ui-button-neutral ui-button-md"
                                disabled=move || busy.get()
                                on:click=move |_| set_visible.set(false)
                            >
                                {t_string!(i18n, common::cancel)}
                            </button>
                            <button
                                class="ui-button ui-button-success ui-button-md"
                                disabled=move || busy.get()
                                on:click=move |_| on_confirm.run(())
                            >
                                {move || if busy.get() {
                                    t_string!(i18n, training::replicating)
                                } else {
                                    t_string!(i18n, training::replicate)
                                }}
                            </button>
                        </div>
                    </div>
                </div>
            }.into_any()
        } else {
            view! { <div/> }.into_any()
        }}
    }
}
