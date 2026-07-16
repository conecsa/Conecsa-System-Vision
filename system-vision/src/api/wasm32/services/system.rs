//! System metrics access (HTTP/JSON).

use crate::api::wasm32::http::fetch_api;
use crate::components::status_component::SystemMetrics;

/// Get system metrics.
pub async fn get_system_metrics() -> Result<SystemMetrics, String> {
    use leptos::logging;

    logging::log!("Fetching system metrics from /api/system/status");
    match fetch_api::<SystemMetrics>("/api/system/status", "GET", None).await {
        Ok(metrics) => {
            logging::log!(
                "System metrics received successfully: CPU={:.1}%, RAM={:.1}%",
                metrics.cpu_usage,
                metrics.ram_usage
            );
            Ok(metrics)
        }
        Err(e) => {
            logging::error!("Failed to fetch system metrics: {}", e);
            Err(e)
        }
    }
}
