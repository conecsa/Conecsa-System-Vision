//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::class_color::{class_color_for, class_display_name};
use crate::i18n::*;

/// Class CRUD + active-class selection. The active class is the one new boxes
/// (and accepted SAM suggestions) are tagged with.
#[component]
pub(super) fn ClassesPanel(
    classes: ReadSignal<Vec<String>>,
    active_class: ReadSignal<usize>,
    set_active_class: WriteSignal<usize>,
    on_add: Callback<String>,
    on_rename: Callback<(usize, String)>,
    on_remove: Callback<usize>,
) -> impl IntoView {
    let i18n = use_i18n();
    let (new_name, set_new_name) = signal(String::new());

    let add = move |_| {
        let name = new_name.get_untracked().trim().to_string();
        if name.is_empty() {
            return;
        }
        on_add.run(name);
        set_new_name.set(String::new());
    };

    let rename = move |index: usize, current: String| {
        let window = web_sys::window();
        let Some(window) = window else { return };
        if let Ok(Some(name)) = window.prompt_with_message_and_default(
            t_string!(i18n, training::new_class_prompt),
            &current,
        ) {
            let name = name.trim().to_string();
            if !name.is_empty() && name != current {
                on_rename.run((index, name));
            }
        }
    };

    let remove = move |index: usize, name: String| {
        let Some(window) = web_sys::window() else {
            return;
        };
        let msg = t_string!(i18n, training::remove_class_confirm, name = name);
        if window.confirm_with_message(&msg).unwrap_or(false) {
            on_remove.run(index);
        }
    };

    view! {
        <div class="ui-card ui-card-pad-sm flex flex-col gap-3">
            <h2 class="ui-card-title">{t!(i18n, training::classes_title)}</h2>

            <div class="flex gap-2">
                <input
                    type="text"
                    class="ui-input ui-input-sm flex-1"
                    placeholder=move || t_string!(i18n, training::new_class_name_placeholder)
                    prop:value=move || new_name.get()
                    on:input=move |ev| set_new_name.set(event_target_value(&ev))
                    on:keydown=move |ev| {
                        if ev.key() == "Enter" {
                            let name = new_name.get_untracked().trim().to_string();
                            if !name.is_empty() {
                                on_add.run(name);
                                set_new_name.set(String::new());
                            }
                        }
                    }
                />
                <button
                    class="ui-button ui-button-primary ui-button-xs"
                    on:click=add
                >
                    {t!(i18n, training::add)}
                </button>
            </div>

            {move || if classes.get().is_empty() {
                view! {
                    <p class="ui-help italic">
                        {t_string!(i18n, training::create_class_hint)}
                    </p>
                }.into_any()
            } else {
                view! {
                    <ul class="flex flex-col gap-1">
                        <For
                            each={move || classes.get().into_iter().enumerate().collect::<Vec<_>>()}
                            key=|(i, name)| (*i, name.clone())
                            children=move |(i, name): (usize, String)| {
                                let display_name = class_display_name(&name);
                                // Rename prefills the raw entry, so the user can
                                // add, edit or drop the "#hex" suffix.
                                let name_rename = name.clone();
                                let name_remove = name.clone();
                                view! {
                                    <li
                                        class=move || format!(
                                            "group ui-row ui-row-sm ui-row-clickable {}",
                                            if active_class.get() == i {
                                                "ui-row-selected"
                                            } else {
                                                ""
                                            }
                                        )
                                        on:click=move |_| set_active_class.set(i)
                                    >
                                        <span
                                            class="w-3 h-3 rounded-full shrink-0"
                                            // `with` borrows the list — `get`
                                            // would clone it once per row.
                                            style=move || classes.with(|c| format!(
                                                "background-color: {}",
                                                class_color_for(i, c),
                                            ))
                                        />
                                        <span class="ui-value flex-1 truncate">{display_name}</span>
                                        <button
                                            class="ui-icon-button p-1 opacity-0 group-hover:opacity-100"
                                            title=move || t_string!(i18n, training::rename_class)
                                            on:click=move |ev| {
                                                ev.stop_propagation();
                                                rename(i, name_rename.clone());
                                            }
                                        >
                                            <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                            </svg>
                                        </button>
                                        <button
                                            class="ui-icon-button ui-icon-button-danger p-1 opacity-0 group-hover:opacity-100"
                                            title=move || t_string!(i18n, training::remove_class)
                                            on:click=move |ev| {
                                                ev.stop_propagation();
                                                remove(i, name_remove.clone());
                                            }
                                        >
                                            <svg class="w-3.5 h-3.5 stroke-current" viewBox="0 0 24 24" fill="none">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                            </svg>
                                        </button>
                                    </li>
                                }
                            }
                        />
                    </ul>
                }.into_any()
            }}
        </div>
    }
}
