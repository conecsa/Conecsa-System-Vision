//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::i18n::*;

/// Name-input modal shared by "New dataset" and "Rename dataset". The gallery
/// owns the state and API calls; this only renders + emits.
#[component]
pub(super) fn DatasetNameModal(
    /// Translated title — passed as a `move || t_string!(...)` closure so it
    /// follows the locale; plain `&str` literals also work.
    #[prop(into)]
    title: TextProp,
    /// Translated call-to-action label (same contract as `title`).
    #[prop(into)]
    cta: TextProp,
    /// Translated label shown while the request is in flight.
    #[prop(into)]
    busy_label: TextProp,
    visible: Signal<bool>,
    name: ReadSignal<String>,
    set_name: WriteSignal<String>,
    busy: ReadSignal<bool>,
    on_submit: Callback<()>,
    on_cancel: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if visible.get() {
            // TextProp is Arc-backed (Clone, not Copy): clone per invocation so
            // the inner closures take owned handles and this stays FnMut.
            let (busy_label, cta) = (busy_label.clone(), cta.clone());
            view! {
                <div class="ui-modal-backdrop">
                    <div class="ui-card ui-card-pad ui-modal">
                        <h3 class="ui-card-title mb-3">{title.get()}</h3>
                        <input
                            type="text"
                            class="ui-input"
                            placeholder=t_string!(i18n, training::dataset_name_placeholder)
                            prop:value=move || name.get()
                            on:input=move |ev| set_name.set(event_target_value(&ev))
                        />
                        <div class="ui-modal-actions">
                            <button
                                class="ui-button ui-button-neutral ui-button-md"
                                on:click=move |_| on_cancel.run(())
                            >
                                {t_string!(i18n, common::cancel)}
                            </button>
                            <button
                                class="ui-button ui-button-success ui-button-md"
                                disabled=move || busy.get()
                                on:click=move |_| on_submit.run(())
                            >
                                {move || if busy.get() { busy_label.get() } else { cta.get() }}
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
