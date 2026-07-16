//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::TrainingJobStatus;
use crate::i18n::*;

/// Full-screen blocking overlay while a training job runs (modeled on the
/// model-conversion overlay): spinner, epoch counter, progress bar, cancel.
#[component]
pub(super) fn TrainingProgressOverlay(
    job: ReadSignal<Option<TrainingJobStatus>>,
    on_cancel: Callback<()>,
    /// Gracefully finish the run early, keeping the best model so far.
    on_finish: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Local confirm gate for "Finish early": the button row swaps to a
    // confirmation prompt before the request is actually sent.
    let confirm_finish = RwSignal::new(false);

    // Drop any pending confirmation once the job leaves "training" (it finished,
    // was canceled, or moved on to uploading) — in an effect, not the render, so
    // reading+writing the flag can't loop.
    Effect::new(move |_| {
        let active = job.get().map(|j| j.status == "training").unwrap_or(false);
        if !active {
            confirm_finish.set(false);
        }
    });

    view! {
        {move || {
            let Some(j) = job.get() else {
                return view! { <div/> }.into_any();
            };
            if !matches!(j.status.as_str(), "preparing" | "training" | "uploading") {
                return view! { <div/> }.into_any();
            }
            let progress = j.progress;
            let epoch_label = if j.total_epochs > 0 && j.epoch > 0 {
                t_string!(i18n, training::epoch_progress, epoch = j.epoch, total = j.total_epochs)
            } else {
                String::new()
            };
            let message = if j.message.is_empty() {
                t_string!(i18n, training::training_model_message, name = j.model_name.clone())
            } else {
                j.message.clone()
            };
            let cancellable = matches!(j.status.as_str(), "preparing" | "training");
            // Graceful early finish only makes sense once epochs are running.
            let finishable = j.status == "training";
            view! {
                <div class="ui-overlay-panel fixed inset-0 z-50 flex flex-col items-center justify-center">
                    <svg class="animate-spin w-10 h-10 ui-accent mb-4" viewBox="0 0 24 24" fill="none">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    <p class="ui-value text-sm mb-1 text-center max-w-sm px-2">
                        {message}
                    </p>
                    {(!epoch_label.is_empty()).then(|| view! {
                        <p class="ui-help mb-3">{epoch_label}</p>
                    })}
                    <div class="w-56 mt-2">
                        <div class="ui-help flex justify-between mb-1">
                            <span>{t_string!(i18n, training::progress)}</span>
                            <span>{format!("{}%", progress)}</span>
                        </div>
                        <div class="ui-progress-track">
                            <div
                                class="ui-progress-bar ui-progress-bar-primary"
                                style=format!("width: {}%", progress)
                            />
                        </div>
                    </div>
                    <p class="ui-help mt-4 italic">
                        {t_string!(i18n, training::keep_tab_open)}
                    </p>
                    {if finishable && confirm_finish.get() {
                        view! {
                            <div class="mt-6 flex flex-col items-center gap-2">
                                <p class="ui-help text-center max-w-xs">
                                    {t_string!(i18n, training::finish_now_question)}
                                </p>
                                <div class="flex gap-2">
                                    <button
                                        class="ui-button ui-button-neutral ui-button-md"
                                        on:click=move |_| confirm_finish.set(false)
                                    >
                                        {t_string!(i18n, training::keep_training)}
                                    </button>
                                    <button
                                        class="ui-button ui-button-success ui-button-md"
                                        on:click=move |_| {
                                            confirm_finish.set(false);
                                            on_finish.run(());
                                        }
                                    >
                                        {t_string!(i18n, training::finish_now)}
                                    </button>
                                </div>
                            </div>
                        }.into_any()
                    } else {
                        view! {
                            <div class="mt-6 flex gap-2">
                                {cancellable.then(|| view! {
                                    <button
                                        class="ui-button ui-button-danger ui-button-md"
                                        on:click=move |_| on_cancel.run(())
                                    >
                                        {t_string!(i18n, training::cancel_training)}
                                    </button>
                                })}
                                {finishable.then(|| view! {
                                    <button
                                        class="ui-button ui-button-primary ui-button-md"
                                        on:click=move |_| confirm_finish.set(true)
                                    >
                                        {t_string!(i18n, training::finish_early)}
                                    </button>
                                })}
                            </div>
                        }.into_any()
                    }}
                </div>
            }.into_any()
        }}
    }
}
