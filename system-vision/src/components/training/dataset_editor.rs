//! Leptos UI components for the web frontend.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use gloo_timers::future::TimeoutFuture;
use js_sys::Date;
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;
use crate::api::{DatasetSummary, LabelBox, SamStatusResponse, TrainingImageInfo, TrainingJobStatus};
use crate::components::configuration::model_conversion::PendingConversion;
use crate::components::control_panel::ViewMode;
use crate::components::PopupMessages;
use crate::i18n::*;

use super::capture_panel::CapturePanel;
use super::classes_panel::ClassesPanel;
use super::gallery::Gallery;
use super::label_editor::LabelEditor;
use super::progress_overlay::TrainingProgressOverlay;
use super::replicate_modal::ReplicateModal;
use super::train_modal::TrainModal;

const MIN_IMAGES_DEFAULT: u32 = 20;

/// Job is active.
fn job_is_active(job: &TrainingJobStatus) -> bool {
    matches!(job.status.as_str(), "preparing" | "training" | "uploading")
}

/// Capture → label → train flow for ONE dataset. Mounted by `TrainingView`
/// when a dataset is opened from the gallery; everything here is scoped by
/// the dataset's id.
#[component]
pub(super) fn DatasetEditor(
    dataset: DatasetSummary,
    on_back: Callback<()>,
    set_current_view: WriteSignal<ViewMode>,
    set_pending_conversion: WriteSignal<Option<PendingConversion>>,
    /// TrainingView's exit-dedup flag: set when this editor exits training
    /// mode itself (training-done handoff) so the parent's defensive cleanup
    /// never fires a second exit that would resume detection mid-conversion.
    exited: Arc<AtomicBool>,
) -> impl IntoView {
    let i18n = use_i18n();
    // Copy-able handle so every closure below can grab the id without
    // clone-per-closure boilerplate.
    let dataset_id = StoredValue::new(dataset.dataset_id.clone());
    let dataset_name = dataset.name.clone();

    let (images, set_images) = signal(Vec::<TrainingImageInfo>::new());
    let (selected, set_selected) = signal(None::<String>);
    let boxes = RwSignal::new(Vec::<LabelBox>::new());
    let (classes, set_classes) = signal(Vec::<String>::new());
    let (active_class, set_active_class) = signal(0usize);
    let (min_images, set_min_images) = signal(MIN_IMAGES_DEFAULT);
    let (cover_image_id, set_cover_image_id) = signal(dataset.cover_image_id.clone());
    let (sam_status, set_sam_status) = signal(None::<SamStatusResponse>);
    let (sam_mode, set_sam_mode) = signal(false);
    let sam_points = RwSignal::new(Vec::<(f32, f32, bool)>::new());
    let (sam_text, set_sam_text) = signal(String::new());
    let (sam_threshold, set_sam_threshold) = signal(0.5f32);
    let (sam_suggestions, set_sam_suggestions) = signal(Vec::<LabelBox>::new());
    let (sam_busy, set_sam_busy) = signal(false);
    let (job, set_job) = signal(None::<TrainingJobStatus>);
    let (show_train_modal, set_show_train_modal) = signal(false);
    let (show_replicate_modal, set_show_replicate_modal) = signal(false);
    let (replica_target, set_replica_target) = signal(None::<String>);
    let (replica_count, set_replica_count) = signal(5u32);
    let (replicating, set_replicating) = signal(false);
    let (capturing, set_capturing) = signal(false);
    let (error_msg, set_error_msg) = signal(String::new());
    let (success_msg, set_success_msg) = signal(String::new());
    let (info_view, set_info_view) = signal(None::<String>);

    // Guards the long-lived polling loop: signals owned by this component are
    // disposed on unmount, so the loop must stop touching them once we leave.
    let alive = Arc::new(AtomicBool::new(true));
    {
        let alive = alive.clone();
        on_cleanup(move || alive.store(false, Ordering::Relaxed));
    }

    // NOTE: every signal write that happens AFTER an `.await` in this
    // component uses the `try_*` variants — the page can unmount (back /
    // training-done handoff) while a request is in flight, and a plain
    // `set()` on a disposed signal panics the whole WASM app.
    let refresh_images = move || {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::list_training_images(&dataset_id.get_value()).await {
                Ok(r) => {
                    let _ = set_images.try_set(r.images);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_load_images, err = e));
                }
            }
        });
    };

    let refresh_classes = move || {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::get_training_classes(&dataset_id.get_value()).await {
                Ok(r) => {
                    let _ = set_classes.try_set(r.classes);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_load_classes, err = e));
                }
            }
        });
    };

    // Initial load.
    spawn_local(async move {
        if let Ok(d) = api::get_training_dataset(&dataset_id.get_value()).await {
            let _ = set_min_images.try_set(d.min_images.max(1));
            let _ = set_cover_image_id.try_set(d.cover_image_id);
        }
    });
    refresh_images();
    refresh_classes();

    // Predictive SAM warm-up: start the cold load (~1min on the Orin) as soon
    // as the dataset is opened so it overlaps the user's first capture and
    // labeling actions instead of blocking the first SAM toggle. Silent — the
    // user has not asked for SAM yet, so a failure only degrades to the old
    // lazy-load-on-toggle path. Duplicate-safe: SamService.load() is
    // idempotent under its lock, so a toggle mid-warm-up simply joins it.
    {
        let alive = alive.clone();
        spawn_local(async move {
            let Ok(s) = api::get_sam_status().await else {
                return;
            };
            if !alive.load(Ordering::Relaxed) {
                return;
            }
            let _ = set_sam_status.try_set(Some(s.clone()));
            if !s.available || s.loaded {
                return;
            }
            // A running job owns the GPU; the backend refuses LoadSam anyway.
            if let Ok(j) = api::get_training_status().await {
                if job_is_active(&j) {
                    return;
                }
            }
            if !alive.load(Ordering::Relaxed) {
                return;
            }
            let _ = api::load_sam().await;
            if !alive.load(Ordering::Relaxed) {
                return;
            }
            if let Ok(s) = api::get_sam_status().await {
                let _ = set_sam_status.try_set(Some(s));
            }
        });
    }

    // Keep active_class within bounds whenever the class list changes, so the
    // class id stamped on new/accepted boxes is always a real class (an
    // out-of-range or empty-list id is what the backend rejects as "Unknown
    // class id"). Defaults to the first class when the list becomes non-empty.
    Effect::new(move |_| {
        let len = classes.get().len();
        if len > 0 {
            set_active_class.update(|c| {
                if *c >= len {
                    *c = len - 1;
                }
            });
        }
    });

    // Poll the training job while this page is mounted. Cheap when idle; on
    // completion it hands the conversion job to the dashboard and exits.
    {
        let alive = alive.clone();
        let exited = exited.clone();
        spawn_local(async move {
            // Seed the baseline: a job that finished in a PREVIOUS session is
            // still reported "done" by the backend. Without seeding, the loop's
            // first comparison (prev_status = "") would treat that stale "done"
            // as a completion on THIS page and instantly bounce back to the
            // dashboard, re-firing the conversion handoff.
            if let Ok(j) = api::get_training_status().await {
                if !alive.load(Ordering::Relaxed) {
                    return;
                }
                let _ = set_job.try_set(Some(j));
            }
            loop {
                TimeoutFuture::new(2_000).await;
                if !alive.load(Ordering::Relaxed) {
                    break;
                }
                let Ok(j) = api::get_training_status().await else {
                    continue;
                };
                if !alive.load(Ordering::Relaxed) {
                    break;
                }
                let prev_status = job
                    .try_get_untracked()
                    .flatten()
                    .map(|w| w.status.clone())
                    .unwrap_or_default();
                match j.status.as_str() {
                    "done" if prev_status != "done" => {
                        let pending =
                            (!j.conversion_job_id.is_empty()).then(|| PendingConversion {
                                job_id: j.conversion_job_id.clone(),
                                filename: format!("{}.pt", j.model_name),
                                started_at_secs: Date::now() / 1000.0,
                            });
                        let _ = set_job.try_set(Some(j));
                        // Claim the exit BEFORE the request, and never release
                        // it (even if the call fails): an unmount while it is
                        // in flight — or a stuck training mode afterwards —
                        // must never be answered by the parent's cleanup with
                        // a resume=true exit while the conversion may hold the
                        // GPU; genuinely stuck states are the orphan
                        // watchdog's job.
                        exited.store(true, Ordering::Relaxed);
                        // Training finished: leave detection stopped — the model
                        // is being converted/optimized and the auto-select will
                        // load the new engine without starting detection.
                        let _ = api::training_exit(false).await;
                        // Parent-owned signals (MainView): safe across our own
                        // unmount, but bail if the loop was cleaned up.
                        if !alive.load(Ordering::Relaxed) {
                            break;
                        }
                        set_pending_conversion.set(pending);
                        set_current_view.set(ViewMode::LiveStream);
                        break;
                    }
                    "failed" if prev_status != "failed" && !prev_status.is_empty() => {
                        let locale = i18n.get_locale_untracked();
                        let _ = set_error_msg.try_set(td_string!(
                            locale,
                            training::training_failed,
                            err = j.error.clone()
                        ));
                        let _ = set_job.try_set(Some(j));
                    }
                    "canceled" if prev_status != "canceled" && !prev_status.is_empty() => {
                        let locale = i18n.get_locale_untracked();
                        let _ = set_success_msg
                            .try_set(td_string!(locale, training::training_canceled).to_string());
                        let _ = set_job.try_set(Some(j));
                    }
                    _ => {
                        let has_job = job.try_get_untracked().flatten().is_some();
                        if job_is_active(&j) || has_job {
                            let _ = set_job.try_set(Some(j));
                        }
                    }
                }
            }
        });
    }

    // ── image selection (autosaves the previous image's labels) ──────────────

    let select_image = Callback::new(move |id: String| {
        let prev = selected.get_untracked();
        if prev.as_deref() == Some(id.as_str()) {
            return;
        }
        let prev_boxes = boxes.get_untracked();
        set_sam_suggestions.set(Vec::new());
        sam_points.set(Vec::new());
        set_selected.set(Some(id.clone()));
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            let ds = dataset_id.get_value();
            if let Some(prev_id) = prev {
                if let Err(e) = api::set_training_labels(&ds, &prev_id, &prev_boxes).await {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_save_labels, err = e));
                }
            }
            match api::get_training_labels(&ds, &id).await {
                Ok(r) => {
                    let _ = boxes.try_set(r.boxes);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_load_labels, err = e));
                }
            }
            if let Ok(r) = api::list_training_images(&ds).await {
                let _ = set_images.try_set(r.images);
            }
        });
    });

    let save_labels = Callback::new(move |notify: bool| {
        let Some(id) = selected.get_untracked() else {
            return;
        };
        let bs = boxes.get_untracked();
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            let ds = dataset_id.get_value();
            match api::set_training_labels(&ds, &id, &bs).await {
                Ok(_) => {
                    if notify {
                        let _ = set_success_msg
                            .try_set(td_string!(locale, training::labels_saved).to_string());
                    }
                    if let Ok(r) = api::list_training_images(&ds).await {
                        let _ = set_images.try_set(r.images);
                    }
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_save_labels, err = e));
                }
            }
        });
    });

    // ── capture / delete / cover ──────────────────────────────────────────────

    let on_capture = Callback::new(move |_: ()| {
        if capturing.get_untracked() {
            return;
        }
        set_capturing.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::capture_training_image(&dataset_id.get_value()).await {
                // Open the fresh capture straight into the editor; `select_image`
                // autosaves the previous image and refreshes the gallery for us.
                Ok(info) => select_image.run(info.image_id),
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::capture_failed, err = e));
                }
            }
            let _ = set_capturing.try_set(false);
        });
    });

    let on_delete = Callback::new(move |id: String| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::delete_training_image(&dataset_id.get_value(), &id).await {
                Ok(_) => {
                    let still_selected =
                        selected.try_get_untracked().flatten().as_deref() == Some(id.as_str());
                    if still_selected {
                        let _ = set_selected.try_set(None);
                        let _ = boxes.try_set(Vec::new());
                        let _ = set_sam_suggestions.try_set(Vec::new());
                        let _ = sam_points.try_set(Vec::new());
                    }
                    refresh_images();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_delete_image, err = e));
                }
            }
        });
    });

    let on_set_cover = Callback::new(move |id: String| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::set_dataset_cover(&dataset_id.get_value(), &id).await {
                Ok(_) => {
                    let _ = set_cover_image_id.try_set(id);
                    let _ = set_success_msg
                        .try_set(td_string!(locale, training::cover_image_set).to_string());
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_set_cover, err = e));
                }
            }
        });
    });

    // ── replicate ──────────────────────────────────────────────────────────────

    let on_replicate = Callback::new(move |id: String| {
        set_replica_target.set(Some(id));
        set_replica_count.set(5);
        set_show_replicate_modal.set(true);
    });

    let on_replicate_confirm = Callback::new(move |_: ()| {
        let Some(id) = replica_target.get_untracked() else {
            return;
        };
        if replicating.get_untracked() {
            return;
        }
        let count = replica_count.get_untracked().clamp(1, 50);
        set_replicating.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::replicate_training_image(&dataset_id.get_value(), &id, count).await {
                Ok(_) => {
                    let _ = set_show_replicate_modal.try_set(false);
                    let _ = set_success_msg.try_set(if count == 1 {
                        td_string!(locale, training::replicas_created_one).to_string()
                    } else {
                        td_string!(locale, training::replicas_created, count = count)
                    });
                    refresh_images();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_replicate_image, err = e));
                }
            }
            let _ = set_replicating.try_set(false);
        });
    });

    // ── classes ───────────────────────────────────────────────────────────────

    let on_class_add = Callback::new(move |name: String| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::add_training_class(&dataset_id.get_value(), &name).await {
                Ok(r) => {
                    let _ = set_active_class.try_set(r.classes.len().saturating_sub(1));
                    let _ = set_classes.try_set(r.classes);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_add_class, err = e));
                }
            }
        });
    });

    let on_class_rename = Callback::new(move |(index, name): (usize, String)| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::rename_training_class(&dataset_id.get_value(), index, &name).await {
                Ok(r) => {
                    let _ = set_classes.try_set(r.classes);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_rename_class, err = e));
                }
            }
        });
    });

    let on_class_remove = Callback::new(move |index: usize| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            let ds = dataset_id.get_value();
            match api::remove_training_class(&ds, index).await {
                Ok(r) => {
                    let len = r.classes.len();
                    let _ = set_classes.try_set(r.classes);
                    let _ = set_active_class.try_update(|c| {
                        if *c >= index && *c > 0 {
                            *c -= 1;
                        }
                        *c = (*c).min(len.saturating_sub(1));
                    });
                    // Labels were reindexed server-side; reload the open image.
                    if let Some(id) = selected.try_get_untracked().flatten() {
                        if let Ok(r) = api::get_training_labels(&ds, &id).await {
                            let _ = boxes.try_set(r.boxes);
                        }
                    }
                    refresh_images();
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_remove_class, err = e));
                }
            }
        });
    });

    // ── SAM-assisted labeling ─────────────────────────────────────────────────

    let on_sam_toggle = Callback::new(move |_: ()| {
        let enabled = !sam_mode.get_untracked();
        set_sam_mode.set(enabled);
        if !enabled {
            sam_points.set(Vec::new());
            return;
        }
        // Lazily load the model on first use.
        let loaded = sam_status
            .get_untracked()
            .map(|s| s.loaded)
            .unwrap_or(false);
        if !loaded {
            set_sam_busy.set(true);
            let locale = i18n.get_locale_untracked();
            spawn_local(async move {
                match api::load_sam().await {
                    Ok(_) => {
                        let _ = set_success_msg
                            .try_set(td_string!(locale, training::sam_model_loaded).to_string());
                    }
                    Err(e) => {
                        let _ = set_error_msg
                            .try_set(td_string!(locale, training::failed_load_sam, err = e));
                        let _ = set_sam_mode.try_set(false);
                    }
                }
                if let Ok(s) = api::get_sam_status().await {
                    let _ = set_sam_status.try_set(Some(s));
                }
                let _ = set_sam_busy.try_set(false);
            });
        }
    });

    let on_sam_suggest = Callback::new(move |_: ()| {
        let Some(id) = selected.get_untracked() else {
            set_error_msg.set(t_string!(i18n, training::select_image_first).to_string());
            return;
        };
        let text = sam_text.get_untracked();
        let points = sam_points.get_untracked();
        if text.trim().is_empty() && points.is_empty() {
            set_error_msg.set(t_string!(i18n, training::sam_prompt_needed).to_string());
            return;
        }
        if sam_busy.get_untracked() {
            return;
        }
        let threshold = sam_threshold.get_untracked();
        set_sam_busy.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::sam_segment(&dataset_id.get_value(), &id, text.trim(), &points, threshold)
                .await
            {
                Ok(r) if r.boxes.is_empty() => {
                    let _ = set_success_msg
                        .try_set(td_string!(locale, training::sam_no_objects).to_string());
                    let _ = set_sam_suggestions.try_set(Vec::new());
                }
                Ok(r) => {
                    let _ = set_sam_suggestions.try_set(r.boxes);
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::segmentation_failed, err = e));
                }
            }
            if let Ok(s) = api::get_sam_status().await {
                let _ = set_sam_status.try_set(Some(s));
            }
            let _ = set_sam_busy.try_set(false);
        });
    });

    let on_sam_accept = Callback::new(move |_: ()| {
        let suggestions = sam_suggestions.get_untracked();
        if suggestions.is_empty() {
            return;
        }
        let Some(image_id) = selected.get_untracked() else {
            set_error_msg.set(t_string!(i18n, training::select_image_first).to_string());
            return;
        };
        // The text prompt IS the class label: accepting "bottle" suggestions
        // tags them as class "bottle" (creating it if needed), NOT the
        // manually-selected active class. Point-only suggestions (no prompt)
        // fall back to the active class.
        let prompt = sam_text.get_untracked().trim().to_string();
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            let ds = dataset_id.get_value();
            let class_id: u32 = if !prompt.is_empty() {
                let existing = classes.try_get_untracked().unwrap_or_default();
                if let Some(idx) = existing
                    .iter()
                    .position(|c| c.eq_ignore_ascii_case(&prompt))
                {
                    idx as u32
                } else {
                    match api::add_training_class(&ds, &prompt).await {
                        Ok(r) => {
                            let id = r
                                .classes
                                .iter()
                                .position(|c| c.eq_ignore_ascii_case(&prompt))
                                .unwrap_or(r.classes.len().saturating_sub(1));
                            let _ = set_classes.try_set(r.classes);
                            let _ = set_active_class.try_set(id);
                            id as u32
                        }
                        Err(e) => {
                            let _ = set_error_msg.try_set(td_string!(
                                locale,
                                training::failed_create_class,
                                name = prompt,
                                err = e
                            ));
                            return;
                        }
                    }
                }
            } else {
                let cls = classes.try_get_untracked().unwrap_or_default();
                if cls.is_empty() {
                    let _ = set_error_msg.try_set(
                        td_string!(locale, training::create_class_before_accepting).to_string(),
                    );
                    return;
                }
                active_class
                    .try_get_untracked()
                    .unwrap_or(0)
                    .min(cls.len() - 1) as u32
            };

            let mut bs = boxes.try_get_untracked().unwrap_or_default();
            bs.extend(suggestions.into_iter().map(|mut b| {
                b.class_id = class_id;
                b
            }));
            let _ = boxes.try_set(bs.clone());
            let _ = set_sam_suggestions.try_set(Vec::new());
            let _ = sam_points.try_set(Vec::new());

            match api::set_training_labels(&ds, &image_id, &bs).await {
                Ok(_) => {
                    if let Ok(r) = api::list_training_images(&ds).await {
                        let _ = set_images.try_set(r.images);
                    }
                }
                Err(e) => {
                    let _ = set_error_msg
                        .try_set(td_string!(locale, training::failed_save_labels, err = e));
                }
            }
        });
    });

    // Surfaced by the editor when the user tries to draw a box with no class.
    let on_need_class = Callback::new(move |_: ()| {
        set_error_msg.set(t_string!(i18n, training::create_class_before_drawing).to_string());
    });

    let on_sam_clear = Callback::new(move |_: ()| {
        set_sam_suggestions.set(Vec::new());
        sam_points.set(Vec::new());
    });

    // ── training ──────────────────────────────────────────────────────────────

    let labeled_count =
        Signal::derive(move || images.get().iter().filter(|i| i.labeled).count() as u32);
    let image_count = Signal::derive(move || images.get().len() as u32);
    let can_train = Signal::derive(move || {
        image_count.get() >= min_images.get()
            && !classes.get().is_empty()
            && labeled_count.get() > 0
    });

    let on_train_request = Callback::new(move |_: ()| {
        // Persist the open image's labels before the gate is evaluated.
        save_labels.run(false);
        set_show_train_modal.set(true);
    });

    let on_train_start = Callback::new(
        move |(name, epochs, batch, patience): (String, u32, u32, u32)| {
            let locale = i18n.get_locale_untracked();
            spawn_local(async move {
                match api::start_training(&dataset_id.get_value(), &name, epochs, batch, patience)
                    .await
                {
                    Ok(j) => {
                        let _ = set_job.try_set(Some(j));
                        let _ = set_show_train_modal.try_set(false);
                    }
                    Err(e) => {
                        let _ = set_error_msg
                            .try_set(td_string!(locale, training::failed_start_training, err = e));
                    }
                }
            });
        },
    );

    let on_train_cancel = Callback::new(move |_: ()| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            if let Err(e) = api::cancel_training().await {
                let _ = set_error_msg
                    .try_set(td_string!(locale, training::failed_cancel_training, err = e));
            }
        });
    });

    let on_train_finish = Callback::new(move |_: ()| {
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            if let Err(e) = api::finish_training().await {
                let _ = set_error_msg
                    .try_set(td_string!(locale, training::failed_finish_training, err = e));
            }
        });
    });

    // ── back to the dataset gallery ───────────────────────────────────────────

    let on_back_click = Callback::new(move |_: ()| {
        if job
            .get_untracked()
            .map(|j| job_is_active(&j))
            .unwrap_or(false)
        {
            set_error_msg.set(t_string!(i18n, training::wait_training_finish).to_string());
            return;
        }
        let prev = selected.get_untracked();
        let prev_boxes = boxes.get_untracked();
        spawn_local(async move {
            // Autosave the open image's labels; stay in training mode (the
            // gallery is still part of the training page).
            if let Some(id) = prev {
                let _ = api::set_training_labels(&dataset_id.get_value(), &id, &prev_boxes).await;
            }
            on_back.run(());
        });
    });

    view! {
        <div class="flex flex-col h-full min-h-0">
            // ── editor bar ──────────────────────────────────────────────────
            <div class="ui-topbar flex items-center justify-between px-4 py-3">
                <div class="flex items-center gap-3">
                    <button
                        class="ui-button ui-button-neutral ui-button-md"
                        on:click=move |_| on_back_click.run(())
                    >
                        "← "
                        {t!(i18n, training::back_to_datasets)}
                    </button>
                    <h1 class="text-lg font-semibold">
                        {dataset_name}
                    </h1>
                </div>
                <div class="flex items-center gap-4">
                    <span class="ui-help text-sm">
                        {move || t_string!(
                            i18n,
                            training::images_counter,
                            count = image_count.get(),
                            labeled = labeled_count.get(),
                            min = min_images.get()
                        )}
                    </span>
                    <button
                        class="ui-button ui-button-success ui-button-md"
                        disabled=move || !can_train.get()
                        title=move || if can_train.get() {
                            t_string!(i18n, training::train_tooltip_ready).to_string()
                        } else {
                            t_string!(
                                i18n,
                                training::train_tooltip_requirements,
                                min = min_images.get()
                            )
                        }
                        on:click=move |_| on_train_request.run(())
                    >
                        {t!(i18n, training::train_model)}
                    </button>
                </div>
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

            // ── body ────────────────────────────────────────────────────────
            <main class="app-main">
                // h-full + min-h-0 per column: the app shell is a fixed
                // viewport (overflow hidden), so each column scrolls on
                // its own instead of pushing past the window bottom.
                <div class="grid grid-cols-12 gap-4 w-full h-full min-h-0">
                    <div class="col-span-3 flex flex-col gap-4 min-h-0 max-h-full overflow-y-auto">
                        <CapturePanel
                            on_capture=on_capture
                            capturing=capturing
                        />
                        <ClassesPanel
                            classes=classes
                            active_class=active_class
                            set_active_class=set_active_class
                            on_add=on_class_add
                            on_rename=on_class_rename
                            on_remove=on_class_remove
                        />
                    </div>

                    <div class="col-span-6 min-h-0 max-h-full overflow-y-auto">
                        <LabelEditor
                            dataset_id=dataset.dataset_id.clone()
                            selected=selected
                            boxes=boxes
                            classes=classes
                            active_class=active_class
                            sam_mode=sam_mode
                            sam_points=sam_points
                            sam_suggestions=sam_suggestions
                            sam_status=sam_status
                            sam_busy=sam_busy
                            sam_text=sam_text
                            set_sam_text=set_sam_text
                            sam_threshold=sam_threshold
                            set_sam_threshold=set_sam_threshold
                            on_sam_toggle=on_sam_toggle
                            on_sam_suggest=on_sam_suggest
                            on_sam_accept=on_sam_accept
                            on_sam_clear=on_sam_clear
                            on_save=save_labels
                            on_need_class=on_need_class
                        />
                    </div>

                    <div class="col-span-3 min-h-0 max-h-full overflow-y-auto">
                        <Gallery
                            dataset_id=dataset.dataset_id.clone()
                            images=images
                            selected=selected
                            cover_image_id=cover_image_id
                            on_select=select_image
                            on_delete=on_delete
                            on_set_cover=on_set_cover
                            on_replicate=on_replicate
                        />
                    </div>
                </div>
            </main>

            <TrainModal
                visible=show_train_modal
                set_visible=set_show_train_modal
                on_start=on_train_start
            />

            <ReplicateModal
                visible=show_replicate_modal
                set_visible=set_show_replicate_modal
                count=replica_count
                set_count=set_replica_count
                busy=replicating
                on_confirm=on_replicate_confirm
            />

            <TrainingProgressOverlay
                job=job
                on_cancel=on_train_cancel
                on_finish=on_train_finish
            />
        </div>
    }
}
