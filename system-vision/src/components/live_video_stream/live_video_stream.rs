//! Leptos UI components for the web frontend.

use crate::app::SystemStatus;
use crate::components::area_chips::AreaView;
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;

use super::video_content::VideoContent;

/// The `LiveVideoStream` view component.
#[component]
pub fn LiveVideoStream(
    status: ReadSignal<Option<SystemStatus>>,
    set_info_view: WriteSignal<Option<String>>,
    // Bumped on model select; detection areas are per-model so we re-fetch
    // them whenever this changes.
    model_refresh: ReadSignal<u32>,
    camera_refresh: ReadSignal<u32>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (reload_key, set_reload_key) = signal(0u32);

    // Full list of areas: drives both the chip strip and the bottom toolbar.
    let (areas, set_areas) = signal(Vec::<AreaView>::new());

    // Shared open-panel id for the stream overlays (0 = none). Keeps the stereo
    // and image-adjustment panels mutually exclusive.
    let panel = RwSignal::new(0u8);

    let editing_id: Signal<Option<String>> = Signal::derive(move || {
        areas
            .get()
            .into_iter()
            .find(|a| a.is_editing)
            .map(|a| a.id.clone())
    });
    let editing_shape: Signal<String> = Signal::derive(move || {
        areas
            .get()
            .into_iter()
            .find(|a| a.is_editing)
            .map(|a| a.shape.clone())
            .unwrap_or_else(|| "rectangle".to_string())
    });

    // ---- state sync --------------------------------------------------------
    let apply_response = move |resp: api::DetectionAreasResponse| {
        let list: Vec<AreaView> = resp
            .areas
            .into_iter()
            .map(|a| AreaView {
                id: a.id,
                is_editing: a.is_editing,
                shape: a.shape,
            })
            .collect();
        set_areas.set(list);
    };

    macro_rules! spawn_api {
        ($api_call:expr $(, $unused:expr)*) => {
            spawn_local(async move {
                if let Ok(resp) = $api_call.await {
                    apply_response(resp);
                }
            });
        };
    }

    // Initial load on mount.
    Effect::new(move |_| {
        spawn_api!(api::list_detection_areas());
    });

    // Re-fetch areas when a different model is selected (areas are per-model).
    // Skip the initial run - the mount Effect above already loads them.
    Effect::new(move |prev: Option<u32>| {
        let key = model_refresh.get();
        if prev.is_some() {
            spawn_api!(api::list_detection_areas());
        }
        key
    });

    // ---- callbacks emitted by the child components -------------------------
    let on_add: Callback<()> = Callback::new(move |_| {
        spawn_api!(api::create_detection_area());
    });

    let on_command: Callback<&'static str> = Callback::new(move |action: &'static str| {
        if let Some(id) = editing_id.get() {
            spawn_api!(api::send_area_command(&id, action), &id, action);
        }
    });

    let on_save: Callback<()> = Callback::new(move |_| {
        if let Some(id) = editing_id.get() {
            spawn_api!(api::save_detection_area(&id), &id);
        }
    });

    let on_cancel_editing: Callback<()> = Callback::new(move |_| {
        if let Some(id) = editing_id.get() {
            spawn_api!(api::discard_detection_area(&id), &id);
        }
    });

    let on_edit_chip: Callback<String> = Callback::new(move |id: String| {
        spawn_api!(api::edit_detection_area(&id), &id);
    });

    let on_delete_chip: Callback<String> = Callback::new(move |id: String| {
        spawn_api!(api::delete_detection_area(&id), &id);
    });

    let on_toggle_shape: Callback<()> = Callback::new(move |_| {
        if let Some(id) = editing_id.get() {
            let next = if editing_shape.get() == "circle" {
                "rectangle"
            } else {
                "circle"
            };
            spawn_api!(api::set_area_shape(&id, next), &id, next);
        }
    });

    view! {
        <div class="ui-card ui-card-pad flex flex-col h-full min-h-0 overflow-hidden">
            <PanelHeader title=move || t_string!(i18n, stream::live_video_stream)>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </PanelHeader>
            <VideoContent
                status=status
                set_info_view=set_info_view
                reload_key=reload_key
                set_reload_key=set_reload_key
                areas=areas
                panel=panel
                model_refresh=model_refresh
                camera_refresh=camera_refresh
                editing_id=editing_id
                editing_shape=editing_shape
                on_add=on_add
                on_edit_chip=on_edit_chip
                on_delete_chip=on_delete_chip
                on_command=on_command
                on_toggle_shape=on_toggle_shape
                on_save=on_save
                on_cancel=on_cancel_editing
            />
        </div>
    }
}
