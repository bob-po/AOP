//! Shared daemon runtime for console and Windows service entrypoints.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

use aop_core::Config;
use aop_supervisor::{serve_mgmt, Supervisor};

use crate::Args;

pub type StopFuture = Pin<Box<dyn Future<Output = ()> + Send>>;

pub async fn run_daemon(args: Args, stop: Option<StopFuture>) -> Result<()> {
    init_tracing(args.service);

    let config_path = args
        .config
        .canonicalize()
        .unwrap_or_else(|_| args.config.clone());
    info!(path = %config_path.display(), service = args.service, "starting aopd");

    // Service cwd is often System32 — prefer config file directory.
    if let Some(dir) = config_path.parent() {
        let _ = std::env::set_current_dir(dir);
    }

    let cfg = if config_path.is_file() {
        Config::load(&config_path)?
    } else {
        warn!(
            path = %config_path.display(),
            "config not found; using built-in example defaults"
        );
        let mut c = Config::example();
        c.plugins_dir = std::env::current_dir()
            .map(|p| p.join("plugins").to_string_lossy().into_owned())
            .unwrap_or_else(|_| "./plugins".into());
        c
    };

    let mgmt_listen = cfg.mgmt_listen.clone();
    let sup = Supervisor::new(cfg)?;
    let config_str = config_path.to_string_lossy().into_owned();

    let mgmt_sup = Arc::clone(&sup);
    let mgmt_handle = tokio::spawn(async move { serve_mgmt(mgmt_sup, config_str).await });

    wait_local_health(&mgmt_listen, 15).await?;

    sup.bootstrap(!args.offline)
        .await
        .context("supervisor bootstrap")?;

    let shutdown = async {
        if let Some(stop) = stop {
            stop.await;
        } else {
            shutdown_signal().await;
        }
    };

    tokio::select! {
        r = mgmt_handle => {
            match r {
                Ok(inner) => inner?,
                Err(e) => anyhow::bail!("mgmt task join: {e}"),
            }
        }
        _ = shutdown => {
            info!("shutdown signal");
            sup.shutdown().await;
        }
    }
    Ok(())
}

fn init_tracing(as_service: bool) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    if as_service {
        // Prefer file log under config dir / LOCALAPPDATA when no console.
        let log_path = dirs_log_path();
        if let Ok(file) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
        {
            let _ = tracing_subscriber::fmt()
                .with_env_filter(filter)
                .with_ansi(false)
                .with_writer(std::sync::Mutex::new(file))
                .try_init();
            return;
        }
    }
    let _ = tracing_subscriber::fmt().with_env_filter(filter).try_init();
}

fn dirs_log_path() -> PathBuf {
    let base = dirs::data_local_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("aop-node");
    let _ = std::fs::create_dir_all(&base);
    base.join("aopd-service.log")
}

async fn wait_local_health(listen: &str, timeout_s: u64) -> Result<()> {
    let url = format!("http://{listen}/health");
    let client = reqwest::Client::new();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(timeout_s);
    let mut last = anyhow::anyhow!("mgmt not ready");
    while tokio::time::Instant::now() < deadline {
        match client.get(&url).send().await {
            Ok(r) if r.status().is_success() => {
                info!(%url, "mgmt HTTP ready");
                return Ok(());
            }
            Ok(r) => last = anyhow::anyhow!("mgmt health {}", r.status()),
            Err(e) => last = e.into(),
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    Err(last.context("timed out waiting for mgmt HTTP"))
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{signal, SignalKind};
        let mut term = signal(SignalKind::terminate()).ok();
        let mut int = signal(SignalKind::interrupt()).ok();
        tokio::select! {
            _ = async { if let Some(s) = term.as_mut() { s.recv().await; } } => {}
            _ = async { if let Some(s) = int.as_mut() { s.recv().await; } } => {}
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}
