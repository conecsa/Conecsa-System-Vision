//! Leptos UI components for the web frontend.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use gloo_timers::future::TimeoutFuture;
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;
use crate::api::DatasetSummary;
use crate::components::configuration::model_conversion::PendingConversion;
use crate::components::control_panel::ViewMode;
use crate::components::PopupMessages;
use crate::i18n::*;

use super::dataset_editor::DatasetEditor;
use super::dataset_gallery::DatasetGallery;

/// Training page shell: the dataset gallery (default) and, once a dataset is
/// opened, the capture/label/train editor scoped to it. Detection stays
/// stopped (GPU handed over) for as long as this page is mounted.
#[component]
pub fn TrainingView(
    set_current_view: WriteSignal<ViewMode>,
    set_pending_conversion: WriteSignal<Option<PendingConversion>>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (open_dataset, set_open_dataset) = signal(None::<DatasetSummary>);
    let (exiting, set_exiting) = signal(false);
    let (error_msg, set_error_msg) = signal(String::new());
    let (success_msg, set_success_msg) = signal(String::new());
    let (info_view, set_info_view) = signal(None::<String>);

    let alive = Arc::new(AtomicBool::new(true));
    // Set by whichever path exits training mode first (exit button, the
    // training-done handoff inside DatasetEditor, or the defensive cleanup
    // below); guarantees exactly one exit call and never a spurious detection
    // resume while a post-training model conversion holds the GPU.
    let exited = Arc::new(AtomicBool::new(false));

    // Heartbeat: labeling is quiet on HTTP and the gateway's orphan-training
    // timeout is short, so tell it this page is still alive while mounted.
    {
        let alive = alive.clone();
        spawn_local(async move {
            loop {
                TimeoutFuture::new(10_000).await;
                if !alive.load(Ordering::Relaxed) {
                    break;
                }
                let _ = api::training_heartbeat().await;
            }
        });
    }

    // Defensive exit: any unmount that did not already exit training mode
    // resumes detection exactly once. Closing the tab / swapping the iframe
    // never runs WASM cleanup — the gateway watchdog is the backstop there.
    {
        let alive = alive.clone();
        let exited = exited.clone();
        on_cleanup(move || {
            alive.store(false, Ordering::Relaxed);
            if !exited.swap(true, Ordering::Relaxed) {
                spawn_local(async move {
                    let _ = api::training_exit(true).await;
                });
            }
        });
    }

    let on_open = Callback::new(move |ds: DatasetSummary| {
        set_open_dataset.set(Some(ds));
    });

    let on_back = Callback::new(move |_: ()| {
        let _ = set_open_dataset.try_set(None);
    });

    // Leave the training page entirely (gallery level only — the editor has
    // its own "Back to datasets" button).
    let exit_flag = exited.clone();
    let on_exit = Callback::new(move |_: ()| {
        if exiting.get_untracked() {
            return;
        }
        set_exiting.set(true);
        let locale = i18n.get_locale_untracked();
        let exited = exit_flag.clone();
        spawn_local(async move {
            // Claim the exit BEFORE the request: an unmount while it is in
            // flight must find the flag already set, or the defensive
            // cleanup would issue a second exit.
            if exited.swap(true, Ordering::Relaxed) {
                return;
            }
            // Manual exit: restore inference detection.
            if let Err(e) = api::training_exit(true).await {
                // Still in training mode: release the claim so a later exit
                // (button retry or cleanup) can go through.
                exited.store(false, Ordering::Relaxed);
                let _ = set_error_msg
                    .try_set(td_string!(locale, training::failed_resume_inference, err = e));
                let _ = set_exiting.try_set(false);
                return;
            }
            set_current_view.set(ViewMode::LiveStream);
        });
    });

    let editor_exited = exited.clone();
    view! {
        <div class="app-scale-viewport">
            <div class="app-scale-content">
                <div class="app-shell">
                    {move || match open_dataset.get() {
                        None => view! {
                            <div class="flex flex-col h-full min-h-0">
                                // ── top bar ─────────────────────────────────
                                <div class="ui-topbar flex items-center justify-between px-4 py-3">
                                    <div class="flex items-center gap-3">
                                        <h1 class="text-lg font-semibold">
                                            {t_string!(i18n, training::page_title)}
                                        </h1>
                                    </div>
                                    <button
                                        class="ui-button ui-button-neutral ui-button-md"
                                        disabled=move || exiting.get()
                                        on:click=move |_| on_exit.run(())
                                    >
                                        <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                                        </svg>
                                        {move || if exiting.get() {
                                            t_string!(i18n, training::resuming_detection)
                                        } else {
                                            t_string!(i18n, training::exit_training)
                                        }}
                                    </button>
                                </div>

                                <div class="app-alert-slot">
                                    <PopupMessages
                                        error_msg=error_msg
                                        success_msg=success_msg
                                        info_view=info_view
                                        set_error_msg=set_error_msg
                                        set_success_msg=set_success_msg
                                        _set_info_view=set_info_view
                                    />
                                </div>

                                <main class="app-main">
                                    <div class="w-full h-full min-h-0 overflow-y-auto">
                                        <DatasetGallery
                                            on_open=on_open
                                            set_error_msg=set_error_msg
                                            set_success_msg=set_success_msg
                                        />
                                    </div>
                                </main>
                            </div>
                        }.into_any(),
                        Some(ds) => view! {
                            <DatasetEditor
                                dataset=ds
                                on_back=on_back
                                set_current_view=set_current_view
                                set_pending_conversion=set_pending_conversion
                                exited=editor_exited.clone()
                            />
                        }.into_any(),
                    }}
                </div>
            </div>
        </div>
    }
}
