//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use super::alert_message::{AlertKind, AlertMessage};
use super::stream_info_message::StreamInfoMessage;

/// Setup auto close.
fn setup_auto_close(msg_signal: ReadSignal<String>, set_msg_signal: WriteSignal<String>) {
    Effect::new(move |_| {
        let msg = msg_signal.get();
        if !msg.is_empty() {
            // Calculate duration: 3 seconds minimum + 0.05 seconds per character, max 5 seconds
            let char_count = msg.chars().count();
            let duration_secs = (3.0 + (char_count as f64 * 0.05)).min(5.0).max(3.0);

            set_timeout(
                move || {
                    set_msg_signal.set(String::new());
                },
                std::time::Duration::from_millis((duration_secs * 1000.0) as u64),
            );
        }
    });
}

/// The `PopupMessages` view component.
#[component]
pub fn PopupMessages(
    error_msg: ReadSignal<String>,
    success_msg: ReadSignal<String>,
    info_view: ReadSignal<Option<String>>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
    _set_info_view: WriteSignal<Option<String>>,
) -> impl IntoView {
    // Auto-close messages after 3-5 seconds (duration based on message length)
    setup_auto_close(error_msg, set_error_msg);
    setup_auto_close(success_msg, set_success_msg);

    view! {
        // The outer box stays zero-height in the normal flow; the messages are
        // absolutely positioned so they float as an overlay over the content
        // below instead of taking layout space and pushing everything down.
        <div class="relative w-full z-50">
            <div class="absolute inset-x-0 top-0 flex flex-col gap-2">
                <AlertMessage message=error_msg kind=AlertKind::Error />
                <AlertMessage message=success_msg kind=AlertKind::Success />
                <StreamInfoMessage info_view=info_view />
            </div>
        </div>
    }
}
