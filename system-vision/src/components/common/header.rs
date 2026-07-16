//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::components::PowerButton;
use crate::i18n::*;

/// The `Header` view component.
#[component]
pub fn Header(api_health: ReadSignal<bool>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <header class="app-header">
            <div class="app-header-inner">
                <div class="app-brand">
                    <img src="/public/conecsa_white_logo.png" alt="CONECSA Logo" class="app-brand-logo" />
                    <div class="app-brand-copy">
                        <p class="app-brand-wordmark">
                            <span>"CONEC"</span>
                            <span class="app-brand-accent">"SA"</span>
                        </p>
                        <p class="app-brand-subtitle">"AUTOMAÇÃO"</p>
                    </div>
                </div>
                <div class="app-product-title">
                    <svg class="w-7 h-7 stroke-current" viewBox="0 0 24 24" fill="none">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                    <h1>"AI System Vision"</h1>
                </div>
                <div class="app-service-status">
                    <span class="text-sm font-medium opacity-85">{t!(i18n, common::inference_service)}</span>
                    <span class={move || if api_health.get() {
                        "app-status-pill app-status-pill-online"
                    } else {
                        "app-status-pill app-status-pill-offline"
                    }}>
                        <span class={move || if api_health.get() {
                            "app-status-dot app-status-dot-online status-dot-pulse"
                        } else {
                            "app-status-dot app-status-dot-offline"
                        }}></span>
                        {move || if api_health.get() {
                            t_string!(i18n, common::connected)
                        } else {
                            t_string!(i18n, common::disconnected)
                        }}
                    </span>
                    <PowerButton />
                </div>
            </div>
        </header>
    }
}
