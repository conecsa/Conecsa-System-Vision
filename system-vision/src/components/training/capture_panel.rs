//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::training_preview_url;
use crate::components::image_adjust_overlay::ImageAdjustOverlay;
use crate::components::stereo_overlay::StereoOverlay;
use crate::i18n::*;

/// Live combined-camera preview + capture button. The preview MJPEG comes from
/// the gateway (CPU-only stereo combine), so it works while inference is
/// stopped; captured frames land in the dataset at 640×640 letterboxed.
///
/// The standard image-adjustment overlay (exposure / RGB / gamma / gain) sits
/// on the preview so the operator can tune the camera before capturing —
/// camera config flows through the inference-service's management gRPC, which
/// stays up while the detection runtime is released.
#[component]
pub(super) fn CapturePanel(on_capture: Callback<()>, capturing: ReadSignal<bool>) -> impl IntoView {
    let i18n = use_i18n();
    let (reload_key, set_reload_key) = signal(0u32);
    let preview_url = move || format!("{}?r={}", training_preview_url(), reload_key.get());

    // The overlay self-fetches on mount; there is no model switching or
    // external camera-change feed on this page, so the refresh triggers are
    // static and the open-panel id is local to this preview.
    let (model_refresh, _) = signal(0u32);
    let (camera_refresh, _) = signal(0u32);
    let panel = RwSignal::new(0u8);

    view! {
        <div class="ui-card ui-card-pad-sm flex flex-col gap-3">
            <h2 class="ui-card-title">{t!(i18n, training::camera_title)}</h2>
            // Outer wrapper anchors the adjustment overlay WITHOUT clipping it
            // (the inner div owns overflow-hidden for the rounded preview), so
            // the panel can extend over the card below the preview.
            <div class="relative">
                <div class="ui-media-bg rounded overflow-hidden aspect-video">
                    <img
                        src=preview_url
                        class="w-full h-full object-contain"
                        alt=move || t_string!(i18n, training::camera_preview_alt)
                        on:error=move |_| {
                            set_timeout(
                                // try_update: the timer can fire after this
                                // page unmounted (signal disposed).
                                move || {
                                    let _ = set_reload_key
                                        .try_update(|k| *k = k.wrapping_add(1));
                                },
                                std::time::Duration::from_millis(1000),
                            );
                        }
                    />
                </div>
                <ImageAdjustOverlay
                    model_refresh=model_refresh
                    camera_refresh=camera_refresh
                    panel=panel
                />
                // Stereo alignment writes to the live camera config; the
                // training preview + captures read that same config, so the
                // sliders reflect here within ~1s.
                <StereoOverlay
                    model_refresh=model_refresh
                    camera_refresh=camera_refresh
                    panel=panel
                />
            </div>
            <button
                class="ui-button ui-button-primary ui-button-md w-full"
                disabled=move || capturing.get()
                on:click=move |_| on_capture.run(())
            >
                <svg class="w-4 h-4 stroke-current" viewBox="0 0 24 24" fill="none">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                {move || if capturing.get() {
                    t_string!(i18n, training::capturing)
                } else {
                    t_string!(i18n, training::capture_image)
                }}
            </button>
        </div>
    }
}
