//! Leptos UI components for the web frontend.

use crate::api;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;
use wasm_bindgen::JsCast;

use super::actions::ClassActions;
use super::editor::ClassEditor;
use super::list::ClassList;

/// The `ClassNames` view component.
#[component]
pub fn ClassNames(
    refresh_classes: ReadSignal<u32>,
    set_error_msg: WriteSignal<String>,
    set_success_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    let privileged = crate::components::access::privileged();
    let classes_file_input_ref = NodeRef::<leptos::html::Input>::new();

    let (classes, set_classes) = signal(Vec::<String>::new());
    let (edit_mode, set_edit_mode) = signal(false);
    let (edited_classes_text, set_edited_classes_text) = signal(String::new());

    // Re-fetch classes on mount and whenever the parent bumps refresh_classes
    // (e.g. after a different model is selected).
    Effect::new(move |_| {
        let _ = refresh_classes.get();
        let locale = i18n.get_locale_untracked();
        spawn_local(async move {
            match api::get_classes().await {
                Ok(cls) => set_classes.set(cls),
                Err(e) => {
                    set_error_msg.set(td_string!(locale, models::failed_to_load_classes, err = e))
                }
            }
        });
    });

    let upload_classes_handler = Callback::new(move |_| {
        if !privileged {
            return;
        }
        if let Some(input) = classes_file_input_ref.get() {
            input.click();
        }
    });

    let on_classes_file_change = move |_| {
        let locale = i18n.get_locale_untracked();
        if let Some(input) = classes_file_input_ref.get() {
            let input_element = input.unchecked_ref::<web_sys::HtmlInputElement>();

            if let Some(files) = input_element.files() {
                if let Some(file) = files.get(0) {
                    let file_name = file.name();

                    if !file_name.ends_with(".txt") {
                        set_error_msg.set(
                            td_string!(locale, models::invalid_file_type_txt).to_string(),
                        );
                        input_element.set_value("");
                        return;
                    }

                    spawn_local(async move {
                        match api::upload_classes_file(file).await {
                            Ok(_) => {
                                set_success_msg.set(td_string!(
                                    locale,
                                    models::classes_uploaded,
                                    name = file_name
                                ));
                                if let Ok(cls) = api::get_classes().await {
                                    set_classes.set(cls);
                                }
                            }
                            Err(e) => {
                                set_error_msg.set(td_string!(
                                    locale,
                                    models::failed_to_upload_classes,
                                    err = e
                                ));
                            }
                        }
                    });

                    input_element.set_value("");
                }
            }
        }
    };

    let start_edit = Callback::new(move |_| {
        set_edited_classes_text.set(classes.get().join("\n"));
        set_edit_mode.set(true);
    });

    let cancel_edit = Callback::new(move |_| {
        set_edit_mode.set(false);
        set_edited_classes_text.set(String::new());
    });

    let save_edit = Callback::new(move |_| {
        let text = edited_classes_text.get();
        let new_classes: Vec<String> = crate::api::parse_classes_text(&text);
        let locale = i18n.get_locale_untracked();

        spawn_local(async move {
            let result = if new_classes.is_empty() {
                api::clear_classes().await
            } else {
                api::upload_classes(new_classes.clone()).await
            };
            match result {
                Ok(_) => {
                    set_success_msg.set(if new_classes.is_empty() {
                        td_string!(locale, models::classes_cleared).to_string()
                    } else {
                        td_string!(locale, models::classes_updated).to_string()
                    });
                    set_classes.set(new_classes);
                    set_edit_mode.set(false);
                    set_edited_classes_text.set(String::new());
                }
                Err(e) => {
                    set_error_msg.set(td_string!(
                        locale,
                        models::failed_to_update_classes,
                        err = e
                    ));
                }
            }
        });
    });

    view! {
        <div class="ui-section-rule mb-4">
            <input
                type="file"
                accept=".txt"
                disabled=!privileged
                node_ref=classes_file_input_ref
                on:change=on_classes_file_change
                style="display: none;"
            />

            <div class="flex flex-wrap justify-between items-center gap-2 mb-2">
                <h3 class="ui-section-title">{t!(i18n, models::class_names_title)}</h3>
                <ClassActions
                    edit_mode=edit_mode
                    on_start_edit=start_edit
                    on_cancel=cancel_edit
                    on_save=save_edit
                    on_upload=upload_classes_handler
                />
            </div>

            {move || if edit_mode.get() {
                view! {
                    <ClassEditor
                        edited_classes_text=edited_classes_text
                        set_edited_classes_text=set_edited_classes_text
                    />
                }.into_any()
            } else {
                view! {
                    <ClassList classes=classes />
                }.into_any()
            }}
        </div>
    }
}
