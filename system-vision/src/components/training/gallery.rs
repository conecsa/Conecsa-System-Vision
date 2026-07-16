//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::api::{training_image_url, TrainingImageInfo};
use crate::i18n::*;

/// Dataset thumbnail grid: select an image for labeling, delete captures,
/// pick the dataset's cover image.
#[component]
pub(super) fn Gallery(
    dataset_id: String,
    images: ReadSignal<Vec<TrainingImageInfo>>,
    selected: ReadSignal<Option<String>>,
    cover_image_id: ReadSignal<String>,
    on_select: Callback<String>,
    on_delete: Callback<String>,
    on_set_cover: Callback<String>,
    on_replicate: Callback<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let dataset_id = StoredValue::new(dataset_id);
    view! {
        <div class="ui-card ui-card-pad-sm flex flex-col gap-3">
            <h2 class="ui-card-title">{t!(i18n, training::dataset_panel_title)}</h2>
            {move || {
                let items = images.get();
                if items.is_empty() {
                    view! {
                        <p class="ui-help italic">
                            {t_string!(i18n, training::no_images_yet)}
                        </p>
                    }.into_any()
                } else {
                    view! {
                        // No inner height cap/scroll: let the grid grow with
                        // the dataset and let the column (max-h-full
                        // overflow-y-auto) own the scrolling, so thumbnails are
                        // never clipped.
                        <div class="grid grid-cols-2 gap-2 pr-1">
                            <For
                                each=move || images.get()
                                key=|img| img.image_id.clone()
                                children=move |img: TrainingImageInfo| {
                                    let box_count = img.box_count;
                                    let id = img.image_id.clone();
                                    let id_select = id.clone();
                                    let id_delete = id.clone();
                                    let id_cover = id.clone();
                                    let id_replicate = id.clone();
                                    let id_is_cover = id.clone();
                                    let is_selected = move || {
                                        selected.get().as_deref() == Some(id.as_str())
                                    };
                                    let is_cover = move || {
                                        cover_image_id.get() == id_is_cover
                                    };
                                    view! {
                                        <div
                                            class=move || format!(
                                                "ui-thumb {}",
                                                if is_selected() {
                                                    "ui-thumb-selected"
                                                } else {
                                                    ""
                                                }
                                            )
                                            on:click=move |_| on_select.run(id_select.clone())
                                        >
                                            <img
                                                src=training_image_url(&dataset_id.get_value(), &img.image_id)
                                                class="ui-media-bg w-full aspect-square object-cover"
                                                alt=move || t_string!(i18n, training::dataset_image_alt)
                                                loading="lazy"
                                            />
                                            {if img.labeled {
                                                view! {
                                                    <span class="ui-badge ui-badge-success absolute bottom-1 left-1 px-1.5 py-0.5 text-[10px]">
                                                        {move || if box_count == 1 {
                                                            t_string!(i18n, training::boxes_badge_one).to_string()
                                                        } else {
                                                            t_string!(i18n, training::boxes_badge, count = box_count)
                                                        }}
                                                    </span>
                                                }.into_any()
                                            } else {
                                                view! {
                                                    <span class="ui-badge ui-badge-muted absolute bottom-1 left-1 px-1.5 py-0.5 text-[10px]">
                                                        {t!(i18n, training::unlabeled_badge)}
                                                    </span>
                                                }.into_any()
                                            }}
                                            {move || if is_cover() {
                                                view! {
                                                    <span class="ui-badge ui-badge-success absolute top-1 left-1 px-1.5 py-0.5 text-[10px]">
                                                        {t_string!(i18n, training::cover_badge)}
                                                    </span>
                                                }.into_any()
                                            } else {
                                                view! { <span/> }.into_any()
                                            }}
                                            {if img.replica {
                                                view! {
                                                    <span
                                                        class="ui-thumb-replica-dot absolute top-1 right-1"
                                                        title=move || t_string!(i18n, training::replicated_image)
                                                    />
                                                }.into_any()
                                            } else {
                                                view! { <span/> }.into_any()
                                            }}
                                            <div class="ui-thumb-actions">
                                                {if img.labeled && !img.replica {
                                                    view! {
                                                        <button
                                                            class="ui-thumb-action"
                                                            title=move || t_string!(i18n, training::replicate_image)
                                                            on:click=move |ev| {
                                                                ev.stop_propagation();
                                                                on_replicate.run(id_replicate.clone());
                                                            }
                                                        >
                                                            <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V5a2 2 0 012-2h9a2 2 0 012 2v9a2 2 0 01-2 2h-2M5 8h9a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2v-9a2 2 0 012-2z" />
                                                            </svg>
                                                        </button>
                                                    }.into_any()
                                                } else {
                                                    view! { <span/> }.into_any()
                                                }}
                                                <button
                                                    class="ui-thumb-action"
                                                    title=move || t_string!(i18n, training::set_as_cover)
                                                    on:click=move |ev| {
                                                        ev.stop_propagation();
                                                        on_set_cover.run(id_cover.clone());
                                                    }
                                                >
                                                    <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.196-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.783-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
                                                    </svg>
                                                </button>
                                                <button
                                                    class="ui-thumb-action ui-thumb-action-danger"
                                                    title=move || t_string!(i18n, training::delete_image)
                                                    on:click=move |ev| {
                                                        ev.stop_propagation();
                                                        on_delete.run(id_delete.clone());
                                                    }
                                                >
                                                    <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                    </svg>
                                                </button>
                                            </div>
                                        </div>
                                    }
                                }
                            />
                        </div>
                    }.into_any()
                }
            }}
        </div>
    }
}
