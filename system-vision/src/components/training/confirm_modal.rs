//! Leptos UI components for the web frontend.

use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;
use crate::components::control_panel::ViewMode;
use crate::i18n::*;

/// Entry gate for the training page: warns that object detection will be
/// stopped, then performs the GPU handover (`POST /api/v1/training/enter`)
/// before switching the view.
#[component]
pub fn TrainingConfirmModal(
    visible: ReadSignal<bool>,
    set_visible: WriteSignal<bool>,
    set_current_view: WriteSignal<ViewMode>,
    set_error_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (busy, set_busy) = signal(false);

    let confirm = move |_| {
        if busy.get_untracked() {
            return;
        }
        set_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::training_enter().await {
                Ok(_) => {
                    set_visible.set(false);
                    set_current_view.set(ViewMode::Training);
                }
                Err(e) => {
                    set_error_msg.set(td_string!(locale, training::failed_enter_training, err = e));
                    set_visible.set(false);
                }
            }
            set_busy.set(false);
        });
    };

    view! {
        {move || if visible.get() {
            view! {
                <div class="ui-modal-backdrop">
                    <div class="ui-card ui-card-pad ui-modal">
                        <div class="flex items-start gap-3">
                            <svg class="ui-warning-icon w-6 h-6 shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                            </svg>
                            <div>
                                <h3 class="ui-card-title mb-2">
                                    {t_string!(i18n, training::open_training_question)}
                                </h3>
                                <p class="ui-help text-sm">
                                    {t_string!(i18n, training::open_training_body)}
                                </p>
                            </div>
                        </div>
                        <div class="flex justify-end gap-2 mt-6">
                            <button
                                class="ui-button ui-button-neutral ui-button-md"
                                on:click=move |_| set_visible.set(false)
                            >
                                {t_string!(i18n, common::cancel)}
                            </button>
                            <button
                                class="ui-button ui-button-warning ui-button-md"
                                disabled=move || busy.get()
                                on:click=confirm
                            >
                                {move || if busy.get() {
                                    t_string!(i18n, training::stopping_detection)
                                } else {
                                    t_string!(i18n, training::stop_detection_and_continue)
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
