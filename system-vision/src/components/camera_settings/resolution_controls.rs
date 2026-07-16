//! Leptos UI components for the web frontend.

use super::{CameraFormat, Resolution, RESOLUTIONS};
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ResolutionControls(
    formats: ReadSignal<Vec<CameraFormat>>,
    selected_res: ReadSignal<Resolution>,
    set_selected_res: WriteSignal<Resolution>,
    selected_framerate: ReadSignal<u32>,
    set_selected_framerate: WriteSignal<u32>,
) -> impl IntoView {
    let i18n = use_i18n();

    view! {
        <div class="flex flex-col gap-1.5">
            <label class="ui-label">
                {t!(i18n, camera::resolution)}
            </label>
            {move || {
                let fmts = formats.get();
                if fmts.is_empty() {
                    view! {
                        <div class="grid grid-cols-2 gap-2">
                            {RESOLUTIONS.iter().map(|(w, h, label, ratio)| {
                                let (rw, rh) = (*w, *h);
                                let label = *label;
                                let ratio = *ratio;
                                view! {
                                    <button
                                        class={move || {
                                            let res = selected_res.get();
                                            if res.w == rw && res.h == rh {
                                                "ui-choice ui-choice-active"
                                            } else {
                                                "ui-choice"
                                            }
                                        }}
                                        on:click=move |_| set_selected_res.set(Resolution { w: rw, h: rh })
                                    >
                                        <span>{label}</span>
                                        <span class="ui-choice-tag">{ratio}</span>
                                    </button>
                                }
                            }).collect::<Vec<_>>()}
                        </div>
                    }.into_any()
                } else {
                    let res = selected_res.get();
                    view! {
                        <select
                            class="ui-select cursor-pointer"
                            on:change=move |ev| {
                                let val = event_target_value(&ev);
                                if let Some((w, h)) = val.split_once('x') {
                                    if let (Ok(w), Ok(h)) = (w.parse::<u32>(), h.parse::<u32>()) {
                                        set_selected_res.set(Resolution { w, h });
                                        if let Some((_, _, fps)) = formats.get().iter().find(|(fw, fh, _)| *fw == w && *fh == h) {
                                            if !fps.contains(&selected_framerate.get()) {
                                                if let Some(&top) = fps.first() {
                                                    set_selected_framerate.set(top);
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        >
                            {fmts.iter().map(|(w, h, _)| {
                                let (w, h) = (*w, *h);
                                let is_sel = res.w == w && res.h == h;
                                view! {
                                    <option value={format!("{}x{}", w, h)} selected={is_sel}>
                                        {format!("{} × {}", w, h)}
                                    </option>
                                }
                            }).collect::<Vec<_>>()}
                        </select>
                    }.into_any()
                }
            }}

            {move || {
                let fmts = formats.get();
                if fmts.is_empty() {
                    return view! { <></> }.into_any();
                }
                let res = selected_res.get();
                let fps_list = fmts.iter()
                    .find(|(w, h, _)| *w == res.w && *h == res.h)
                    .map(|(_, _, f)| f.clone())
                    .unwrap_or_default();
                view! {
                    <label class="ui-label mt-2">
                        {t_string!(i18n, camera::frame_rate)}
                    </label>
                    <select
                        class="ui-select cursor-pointer"
                        on:change=move |ev| {
                            if let Ok(v) = event_target_value(&ev).parse::<u32>() {
                                set_selected_framerate.set(v);
                            }
                        }
                    >
                        {fps_list.iter().map(|f| {
                            let f = *f;
                            let is_sel = selected_framerate.get() == f;
                            view! {
                                <option value={f.to_string()} selected={is_sel}>
                                    {format!("{} fps", f)}
                                </option>
                            }
                        }).collect::<Vec<_>>()}
                    </select>
                }.into_any()
            }}

            <p class="ui-help">
                {t!(i18n, camera::resolution_help)}
            </p>
        </div>
    }
}
