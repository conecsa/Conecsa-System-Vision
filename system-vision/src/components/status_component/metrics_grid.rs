//! Leptos UI components for the web frontend.

use super::metric_card::MetricCard;
use super::SystemMetrics;
use crate::i18n::*;
use leptos::prelude::*;

/// Bytes to gb.
fn bytes_to_gb(value: u64) -> f64 {
    value as f64 / 1024.0 / 1024.0 / 1024.0
}

#[component]
pub(super) fn SystemMetricsGrid(status: ReadSignal<SystemMetrics>) -> impl IntoView {
    let i18n = use_i18n();
    let cpu_value = Signal::derive(move || format!("{:.1}%", status.get().cpu_usage));
    let cpu_usage = Signal::derive(move || status.get().cpu_usage);
    let cpu_detail = Signal::derive(move || {
        let temp = status
            .get()
            .temperature
            .map(|temp| format!("{:.1}°C", temp))
            .unwrap_or_else(|| t_string!(i18n, main::not_available).to_string());
        t_string!(i18n, main::cpu_temp, temp = temp)
    });

    let ram_value = Signal::derive(move || format!("{:.1}%", status.get().ram_usage));
    let ram_usage = Signal::derive(move || status.get().ram_usage);
    let ram_detail = Signal::derive(move || {
        let snapshot = status.get();
        format!(
            "{:.2} GB / {:.2} GB",
            bytes_to_gb(snapshot.ram_used),
            bytes_to_gb(snapshot.ram_total)
        )
    });

    let disk_value = Signal::derive(move || format!("{:.1}%", status.get().disk_usage));
    let disk_usage = Signal::derive(move || status.get().disk_usage);
    let disk_detail = Signal::derive(move || {
        let snapshot = status.get();
        format!(
            "{:.2} GB / {:.2} GB",
            bytes_to_gb(snapshot.disk_used),
            bytes_to_gb(snapshot.disk_total)
        )
    });

    let gpu_value = Signal::derive(move || {
        status
            .get()
            .gpu_usage
            .map(|gpu| format!("{:.1}%", gpu))
            .unwrap_or_else(|| t_string!(i18n, main::not_available).to_string())
    });
    let gpu_usage = Signal::derive(move || status.get().gpu_usage.unwrap_or(0.0));
    let gpu_detail = Signal::derive(move || {
        let snapshot = status.get();
        let freq = snapshot
            .gpu_freq_mhz
            .map(|v| format!("{:.0}", v))
            .unwrap_or_else(|| t_string!(i18n, main::not_available).to_string());
        let max = snapshot
            .gpu_max_freq_mhz
            .map(|v| format!("{:.0}", v))
            .unwrap_or_else(|| t_string!(i18n, main::not_available).to_string());
        let temp = snapshot
            .gpu_temperature
            .map(|v| format!("{:.1}°C", v))
            .unwrap_or_else(|| t_string!(i18n, main::not_available).to_string());
        format!("{} / {} MHz • {}", freq, max, temp)
    });

    view! {
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard label="CPU" value=cpu_value usage=cpu_usage detail=cpu_detail />
            <MetricCard label="RAM" value=ram_value usage=ram_usage detail=ram_detail />
            <MetricCard
                label=move || t_string!(i18n, main::disk_label)
                value=disk_value
                usage=disk_usage
                detail=disk_detail
            />
            <MetricCard label="GPU" value=gpu_value usage=gpu_usage detail=gpu_detail />
        </div>
    }
}
