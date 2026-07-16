//! Backend access layer (HTTP/SSE on wasm, Tauri IPC on native).

use crate::api::wasm32::http::fetch_api;

/// IPv4 configuration of a single managed interface (wired or wireless).
#[derive(Debug, Clone, serde::Deserialize)]
pub struct InterfaceConfig {
    #[serde(default)]
    pub name: String,
    #[serde(default = "default_method")]
    pub method: String,
    pub address: Option<String>,
    pub prefix: Option<u8>,
    pub gateway: Option<String>,
    #[serde(default)]
    pub dns: Vec<String>,
    #[serde(default)]
    pub present: bool,
}

/// Default method.
fn default_method() -> String {
    "auto".to_string()
}

/// Current Wi-Fi association state.
#[derive(Debug, Clone, Default, serde::Deserialize)]
pub struct WifiStatus {
    #[serde(default)]
    pub ssid: String,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub signal: i32,
}

/// Response from GET /api/v1/network/config (wired + Wi-Fi).
#[derive(Debug, Clone, serde::Deserialize)]
pub struct NetworkConfig {
    pub wired: InterfaceConfig,
    pub wifi: InterfaceConfig,
    #[serde(default)]
    pub wifi_status: WifiStatus,
}

/// Response from the IP-config POST endpoint.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct NetworkSetResponse {
    pub success: bool,
    pub message: String,
}

/// A single Wi-Fi network from a scan.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct WifiNetwork {
    pub ssid: String,
    #[serde(default)]
    pub signal: i32,
    #[serde(default)]
    pub security: String,
    #[serde(default)]
    pub in_use: bool,
    #[serde(default)]
    pub saved: bool,
}

/// A `WifiScanResponse` struct.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct WifiScanResponse {
    #[serde(default)]
    pub networks: Vec<WifiNetwork>,
}

/// A `WifiConnectResponse` struct.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct WifiConnectResponse {
    pub success: bool,
    #[serde(default)]
    pub state: String,
    pub message: String,
}

/// GET /api/v1/network/config
pub async fn get_network_config() -> Result<NetworkConfig, String> {
    fetch_api::<NetworkConfig>("/api/v1/network/config", "GET", None).await
}

/// POST /api/v1/network/config — applies an IPv4 configuration to `interface`
/// ("wired" | "wifi").
pub async fn set_network_config(
    interface: String,
    method: String,
    address: Option<String>,
    prefix: Option<u8>,
    gateway: Option<String>,
    dns: Vec<String>,
) -> Result<NetworkSetResponse, String> {
    let body = serde_json::json!({
        "interface": interface,
        "method": method,
        "address": address,
        "prefix": prefix,
        "gateway": gateway,
        "dns": dns,
    })
    .to_string();
    fetch_api::<NetworkSetResponse>("/api/v1/network/config", "POST", Some(&body)).await
}

/// GET /api/v1/network/wifi/scan — lists available Wi-Fi networks.
pub async fn scan_wifi() -> Result<WifiScanResponse, String> {
    fetch_api::<WifiScanResponse>("/api/v1/network/wifi/scan", "GET", None).await
}

/// POST /api/v1/network/wifi/connect — connects and verifies the password.
pub async fn connect_wifi(ssid: String, password: String) -> Result<WifiConnectResponse, String> {
    let body = serde_json::json!({ "ssid": ssid, "password": password }).to_string();
    fetch_api::<WifiConnectResponse>("/api/v1/network/wifi/connect", "POST", Some(&body)).await
}

/// POST /api/v1/network/wifi/forget — removes a saved Wi-Fi network.
pub async fn forget_wifi(ssid: String) -> Result<NetworkSetResponse, String> {
    let body = serde_json::json!({ "ssid": ssid }).to_string();
    fetch_api::<NetworkSetResponse>("/api/v1/network/wifi/forget", "POST", Some(&body)).await
}
