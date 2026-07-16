//! Leptos UI components for the web frontend.

use crate::api;
use crate::app::{load_models, ModelInfo};
use crate::i18n::*;
use leptos::prelude::*;

use gloo_timers::future::TimeoutFuture;
use js_sys::Date;

/// A conversion job started outside the Configuration panel (e.g. the
/// training-service uploading its trained model). MainView hands it to
/// Configuration, which attaches the standard overlay + poll to it.
#[derive(Debug, Clone, PartialEq)]
pub struct PendingConversion {
    pub job_id: String,
    /// Display name for the success/error messages (the model filename).
    pub filename: String,
    pub started_at_secs: f64,
}

/// Configuration for a conversion polling session.
pub struct ConversionPollConfig {
    pub job_id: String,
    pub started_at_secs: f64,
    /// Display name used in the success/timeout messages (original filename).
    pub original_filename: String,
    /// Hard timeout in seconds before the poll is aborted.
    pub timeout_secs: f64,
    /// Maximum value (0–100) the time-based progress bar can reach while polling.
    pub progress_cap: f64,
    /// Locale captured by the caller (untracked) for the user-facing messages.
    pub locale: Locale,
}

/// Polls a running conversion job, updating overlay signals on each tick, and
/// resolves the result (success / failure / timeout) when the job finishes.
///
/// The overlay signals are intentionally owned by the parent (`Configuration`)
/// so the overlay covers the full panel — this function only *writes* to them.
pub async fn poll_conversion_job(
    cfg: ConversionPollConfig,
    set_active_job_id: WriteSignal<Option<String>>,
    set_overlay_message: WriteSignal<String>,
    set_overlay_progress: WriteSignal<u8>,
    set_success_msg: WriteSignal<String>,
    set_error_msg: WriteSignal<String>,
    set_models: WriteSignal<Vec<ModelInfo>>,
    set_model_refresh: WriteSignal<u32>,
) {
    let timeout_label = format!("{}", (cfg.timeout_secs / 60.0).round() as u64);

    loop {
        TimeoutFuture::new(2_000).await;

        let elapsed = Date::now() / 1000.0 - cfg.started_at_secs;
        let time_progress = ((elapsed / 420.0) * 100.0).min(cfg.progress_cap) as u8;

        if elapsed > cfg.timeout_secs {
            set_active_job_id.set(None);
            set_error_msg.set(td_string!(
                cfg.locale,
                models::conversion_timed_out,
                minutes = timeout_label.clone()
            ));
            break;
        }

        match api::get_conversion_status(&cfg.job_id).await {
            Ok(status) => {
                let finished = matches!(status.status.as_str(), "done" | "failed");
                let engine_name = status
                    .auto_select_hint
                    .clone()
                    .or_else(|| status.engine_filename.clone())
                    .unwrap_or_default();
                let error_msg = status.error.clone().unwrap_or_default();
                let status_str = status.status.clone();

                set_overlay_message.set(status.message.clone());
                set_overlay_progress.set(time_progress);

                if finished {
                    set_active_job_id.set(None);
                    if status_str == "done" {
                        if !engine_name.is_empty() {
                            let _ = api::select_model(&engine_name).await;
                        }
                        set_success_msg.set(td_string!(
                            cfg.locale,
                            models::conversion_success,
                            name = cfg.original_filename.clone()
                        ));
                        load_models(set_models, set_error_msg, cfg.locale).await;
                        set_model_refresh.update(|n| *n = n.wrapping_add(1));
                    } else {
                        set_error_msg.set(td_string!(
                            cfg.locale,
                            models::conversion_failed,
                            err = error_msg
                        ));
                    }
                    break;
                }
            }
            Err(e) => {
                set_active_job_id.set(None);
                set_error_msg.set(td_string!(
                    cfg.locale,
                    models::failed_to_poll_conversion,
                    err = e
                ));
                break;
            }
        }
    }
}
