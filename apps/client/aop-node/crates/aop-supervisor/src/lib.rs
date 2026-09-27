//! Supervisor: OS connect + heartbeat + child lifecycle + whitelist exec + mgmt HTTP.

mod api;
mod lifecycle;
mod os_client;

pub use api::serve_mgmt;
pub use lifecycle::Supervisor;
pub use os_client::OsClient;
