//! aopd — AOP Node Supervisor daemon (console or Windows service).

mod run;

use std::path::PathBuf;

use anyhow::Result;
use clap::Parser;

#[derive(Parser, Debug, Clone)]
#[command(name = "aopd", version, about = "AOP Node Supervisor daemon")]
pub struct Args {
    /// Path to aop-node.toml
    #[arg(short, long, env = "AOP_NODE_CONFIG", default_value = "aop-node.toml")]
    pub config: PathBuf,

    /// Run under Windows Service Control Manager (required for `sc start`)
    #[arg(long, default_value_t = false)]
    pub service: bool,

    /// Skip Gateway register / heartbeat (local-only)
    #[arg(long, default_value_t = false)]
    pub offline: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();

    #[cfg(windows)]
    if args.service {
        return windows_svc::run_as_service(args);
    }

    // Interactive / console mode
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    rt.block_on(run::run_daemon(args, None))
}

#[cfg(windows)]
mod windows_svc {
    use std::ffi::OsString;
    use std::sync::mpsc;
    use std::time::Duration;

    use anyhow::{anyhow, Result};
    use clap::Parser;
    use windows_service::{
        define_windows_service,
        service::{
            ServiceControl, ServiceControlAccept, ServiceExitCode, ServiceState, ServiceStatus,
            ServiceType,
        },
        service_control_handler::{self, ServiceControlHandlerResult},
        service_dispatcher,
    };

    use super::Args;

    const SERVICE_NAME: &str = "aop-node";

    define_windows_service!(ffi_service_main, service_main);

    pub fn run_as_service(_args: Args) -> Result<()> {
        // SCM re-invokes us; CLI args are passed again via service binary path.
        service_dispatcher::start(SERVICE_NAME, ffi_service_main)
            .map_err(|e| anyhow!("service dispatcher: {e}"))
    }

    fn service_main(_args: Vec<OsString>) {
        if let Err(e) = run_service() {
            // Best-effort log; Event Log optional later.
            eprintln!("aopd service error: {e:#}");
        }
    }

    fn run_service() -> Result<()> {
        let (shutdown_tx, shutdown_rx) = mpsc::channel::<()>();

        let status_handle = service_control_handler::register(SERVICE_NAME, move |event| {
            match event {
                ServiceControl::Stop | ServiceControl::Shutdown => {
                    let _ = shutdown_tx.send(());
                    ServiceControlHandlerResult::NoError
                }
                ServiceControl::Interrogate => ServiceControlHandlerResult::NoError,
                _ => ServiceControlHandlerResult::NotImplemented,
            }
        })
        .map_err(|e| anyhow!("register service handler: {e}"))?;

        status_handle
            .set_service_status(ServiceStatus {
                service_type: ServiceType::OWN_PROCESS,
                current_state: ServiceState::StartPending,
                controls_accepted: ServiceControlAccept::empty(),
                exit_code: ServiceExitCode::Win32(0),
                checkpoint: 1,
                wait_hint: Duration::from_secs(30),
                process_id: None,
            })
            .map_err(|e| anyhow!("set StartPending: {e}"))?;

        // Re-parse args from process command line (sc binPath).
        let args = Args::parse();

        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()?;

        status_handle
            .set_service_status(ServiceStatus {
                service_type: ServiceType::OWN_PROCESS,
                current_state: ServiceState::Running,
                controls_accepted: ServiceControlAccept::STOP | ServiceControlAccept::SHUTDOWN,
                exit_code: ServiceExitCode::Win32(0),
                checkpoint: 0,
                wait_hint: Duration::default(),
                process_id: None,
            })
            .map_err(|e| anyhow!("set Running: {e}"))?;

        let stop = async move {
            loop {
                if shutdown_rx.try_recv().is_ok() {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(400)).await;
            }
        };

        let result = rt.block_on(crate::run::run_daemon(args, Some(Box::pin(stop))));

        let _ = status_handle.set_service_status(ServiceStatus {
            service_type: ServiceType::OWN_PROCESS,
            current_state: ServiceState::Stopped,
            controls_accepted: ServiceControlAccept::empty(),
            exit_code: ServiceExitCode::Win32(0),
            checkpoint: 0,
            wait_hint: Duration::default(),
            process_id: None,
        });

        result
    }
}
