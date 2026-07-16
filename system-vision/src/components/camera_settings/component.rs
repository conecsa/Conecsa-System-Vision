//! Leptos UI components for the web frontend.

use crate::api;
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::apply_button::ApplyCameraSettingsButton;
use super::device_select::CaptureDeviceSelect;
use super::loading_state::CameraSettingsLoadingState;
use super::resolution_controls::ResolutionControls;
use super::stereo_toggle::StereoOverlayToggle;
use super::{CameraFormat, Resolution};

/// Push only the stereo combine settings. Applied immediately (no camera
/// restart, since stereo lives in the inference-service, not the SHM config).
fn push_stereo_enabled(enabled: bool) {
    spawn_local(async move {
        let _ = api::update_stereo_config(Some(enabled), None, None, None).await;
    });
}

/// The `CameraSettings` view component.
#[component]
pub fn CameraSettings(
    refresh_camera: ReadSignal<u32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();

    // Device list: (index, label)
    let (devices, set_devices) = signal(Vec::<(u32, String)>::new());
    let (selected_index, set_selected_index) = signal(0u32);
    let (selected_res, set_selected_res) = signal(Resolution { w: 640, h: 480 });
    // Supported (width, height, [fps...]) combinations reported by the camera.
    // When non-empty the UI shows real dropdowns instead of the static presets.
    let (formats, set_formats) = signal(Vec::<CameraFormat>::new());
    let (selected_framerate, set_selected_framerate) = signal(30u32);
    let (selected_stereo_enabled, set_selected_stereo_enabled) = signal(false);
    let (loading, set_loading) = signal(true);
    let (saving, set_saving) = signal(false);

    // A side-by-side stereo camera packs both eyes horizontally, so a stereo
    // resolution is at least twice as wide as it is tall (w >= 2*h). Only then
    // can each split half stay landscape; a narrower frame would produce a
    // portrait per-eye image the detector's letterbox can't handle.
    let stereo_supported = Signal::derive(move || {
        let r = selected_res.get();
        r.h > 0 && r.w >= 2 * r.h
    });

    // Never leave the overlay enabled on a non-stereo resolution.
    Effect::new(move |_| {
        if !stereo_supported.get() && selected_stereo_enabled.get_untracked() {
            set_selected_stereo_enabled.set(false);
            push_stereo_enabled(false);
        }
    });

    let reload_camera = move || {
        set_loading.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::get_camera_devices().await {
                Ok(resp) => {
                    let list: Vec<(u32, String)> = resp
                        .devices
                        .iter()
                        .map(|d| {
                            let idx = if d.index >= 0 { d.index as u32 } else { 0 };
                            let label = if !d.name.is_empty() && d.name != d.path {
                                format!("{} ({})", d.name, d.path)
                            } else {
                                d.path.clone()
                            };
                            (idx, label)
                        })
                        .collect();
                    set_devices.set(list);
                    set_selected_index.set(resp.current_index);
                    set_selected_res.set(Resolution {
                        w: resp.current_width,
                        h: resp.current_height,
                    });

                    // Prefer MJPG (the high-fps path); merge fps lists per resolution.
                    let mut map: std::collections::BTreeMap<(u32, u32), Vec<u32>> =
                        std::collections::BTreeMap::new();
                    if let Some(dev) = resp
                        .devices
                        .iter()
                        .find(|d| d.index == resp.current_index as i32)
                    {
                        let has_mjpg = dev
                            .supported_formats
                            .iter()
                            .any(|f| f.format.eq_ignore_ascii_case("MJPG"));
                        for f in &dev.supported_formats {
                            if has_mjpg && !f.format.eq_ignore_ascii_case("MJPG") {
                                continue;
                            }
                            let entry = map.entry((f.width, f.height)).or_default();
                            for &v in &f.fps {
                                if !entry.contains(&v) {
                                    entry.push(v);
                                }
                            }
                        }
                    }
                    let mut fmt_list: Vec<CameraFormat> = map
                        .into_iter()
                        .map(|((w, h), mut fps)| {
                            fps.sort_unstable_by(|a, b| b.cmp(a));
                            (w, h, fps)
                        })
                        .collect();
                    fmt_list.sort_by(|a, b| (b.0 * b.1).cmp(&(a.0 * a.1)));
                    set_formats.set(fmt_list);
                    set_selected_framerate.set(resp.current_framerate);
                    set_selected_stereo_enabled.set(resp.current_stereo_enabled);

                    set_loading.set(false);
                }
                Err(e) => {
                    set_error_msg.set(td_string!(locale, camera::failed_to_load_info, err = e));
                    set_loading.set(false);
                }
            }
        });
    };

    Effect::new(move |_| {
        let _ = refresh_camera.get();
        reload_camera();
    });

    // Applies device / resolution / framerate (the fields that restart capture).
    // Exposure, RGB, gamma and gain are adjusted live from the live-video overlay.
    let apply = Callback::new(move |_| {
        let idx = selected_index.get();
        let res = selected_res.get();
        let framerate = selected_framerate.get();
        set_saving.set(true);
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::update_camera_config(
                Some(idx),
                Some(res.w),
                Some(res.h),
                Some(framerate),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            .await
            {
                Ok(_) => {
                    set_success_msg
                        .set(td_string!(locale, camera::settings_applied).to_string());
                    reload_camera();
                }
                Err(e) => {
                    set_error_msg.set(td_string!(locale, camera::failed_to_apply, err = e))
                }
            }
            set_saving.set(false);
        });
    });

    let push_stereo = Callback::new(move |enabled: bool| push_stereo_enabled(enabled));

    view! {
        <div class="ui-card ui-card-pad ui-card-scroll h-full">
            <PanelHeader title=move || t_string!(i18n, camera::title)>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </PanelHeader>

            {move || if loading.get() {
                view! { <CameraSettingsLoadingState /> }.into_any()
            } else {
                view! {
                    <div class="flex flex-col gap-6">
                        <CaptureDeviceSelect
                            devices=devices
                            selected_index=selected_index
                            set_selected_index=set_selected_index
                        />
                        <ResolutionControls
                            formats=formats
                            selected_res=selected_res
                            set_selected_res=set_selected_res
                            selected_framerate=selected_framerate
                            set_selected_framerate=set_selected_framerate
                        />
                        <StereoOverlayToggle
                            stereo_supported=stereo_supported
                            selected_stereo_enabled=selected_stereo_enabled
                            set_selected_stereo_enabled=set_selected_stereo_enabled
                            on_push=push_stereo
                        />
                        <ApplyCameraSettingsButton saving=saving on_apply=apply />
                    </div>
                }.into_any()
            }}
        </div>
    }
}
