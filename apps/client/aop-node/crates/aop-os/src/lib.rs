//! OS-level helpers: child processes, log tails, service install, self-update.

mod logs;
mod process;
mod service;
mod update;

pub use logs::{read_log_tail, LogHub};
pub use process::{ChildHandle, ProcessManager, SpawnSpec};
pub use service::{install_service, service_status, uninstall_service, ServiceKind};
pub use update::{check_and_apply_update, UpdateManifest, UpdateStatus};
