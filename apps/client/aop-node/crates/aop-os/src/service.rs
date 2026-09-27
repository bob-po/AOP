//! Install / uninstall OS service wrappers (Windows sc.exe / Linux systemd).

use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};
use serde::Serialize;

pub const SERVICE_NAME: &str = "aop-node";

#[derive(Debug, Clone, Copy)]
pub enum ServiceKind {
    Windows,
    Systemd,
}

impl ServiceKind {
    pub fn detect() -> Self {
        if cfg!(windows) {
            Self::Windows
        } else {
            Self::Systemd
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ServiceStatus {
    pub kind: String,
    pub name: String,
    pub installed: bool,
    pub detail: String,
}

fn current_exe() -> Result<PathBuf> {
    env::current_exe().context("resolve current exe")
}

/// Prefer `aopd` next to CLI, else current exe.
pub fn resolve_aopd_path() -> Result<PathBuf> {
    let exe = current_exe()?;
    if let Some(dir) = exe.parent() {
        let candidate = if cfg!(windows) {
            dir.join("aopd.exe")
        } else {
            dir.join("aopd")
        };
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    // When running as aopd already
    if exe
        .file_stem()
        .and_then(|s| s.to_str())
        .map(|s| s.eq_ignore_ascii_case("aopd"))
        .unwrap_or(false)
    {
        return Ok(exe);
    }
    Ok(exe)
}

pub fn install_service(config_path: &str) -> Result<String> {
    let aopd = resolve_aopd_path()?;
    let cfg = fs::canonicalize(config_path).unwrap_or_else(|_| PathBuf::from(config_path));
    match ServiceKind::detect() {
        ServiceKind::Windows => install_windows(&aopd, &cfg),
        ServiceKind::Systemd => install_systemd(&aopd, &cfg),
    }
}

pub fn uninstall_service() -> Result<String> {
    match ServiceKind::detect() {
        ServiceKind::Windows => uninstall_windows(),
        ServiceKind::Systemd => uninstall_systemd(),
    }
}

pub fn service_status() -> Result<ServiceStatus> {
    match ServiceKind::detect() {
        ServiceKind::Windows => status_windows(),
        ServiceKind::Systemd => status_systemd(),
    }
}

fn install_windows(aopd: &PathBuf, cfg: &PathBuf) -> Result<String> {
    let bin = aopd.display().to_string();
    let conf = cfg.display().to_string();
    // sc create requires admin. binPath includes args.
    let bin_path = format!("\"{bin}\" --config \"{conf}\" --service");
    let out = Command::new("sc")
        .args([
            "create",
            SERVICE_NAME,
            &format!("binPath= {bin_path}"),
            "start= auto",
            "DisplayName= AOP Node Supervisor",
        ])
        .output()
        .context("run sc create")?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let stdout = String::from_utf8_lossy(&out.stdout);
        bail!("sc create failed: {stdout}{err}");
    }
    let _ = Command::new("sc")
        .args(["description", SERVICE_NAME, "AOP Node Supervisor (aopd)"])
        .output();
    Ok(format!(
        "Windows service '{SERVICE_NAME}' installed. Start with: sc start {SERVICE_NAME} (admin)"
    ))
}

fn uninstall_windows() -> Result<String> {
    let _ = Command::new("sc").args(["stop", SERVICE_NAME]).output();
    let out = Command::new("sc")
        .args(["delete", SERVICE_NAME])
        .output()
        .context("run sc delete")?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        let stdout = String::from_utf8_lossy(&out.stdout);
        bail!("sc delete failed: {stdout}{err}");
    }
    Ok(format!("Windows service '{SERVICE_NAME}' deleted"))
}

fn status_windows() -> Result<ServiceStatus> {
    let out = Command::new("sc")
        .args(["query", SERVICE_NAME])
        .output()
        .context("sc query")?;
    let detail = String::from_utf8_lossy(&out.stdout).to_string()
        + &String::from_utf8_lossy(&out.stderr);
    Ok(ServiceStatus {
        kind: "windows".into(),
        name: SERVICE_NAME.into(),
        installed: out.status.success(),
        detail,
    })
}

fn install_systemd(aopd: &PathBuf, cfg: &PathBuf) -> Result<String> {
    let unit = format!(
        r#"[Unit]
Description=AOP Node Supervisor
After=network.target

[Service]
Type=simple
ExecStart={aopd} --config {cfg}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"#,
        aopd = aopd.display(),
        cfg = cfg.display()
    );
    let path = PathBuf::from(format!("/etc/systemd/system/{SERVICE_NAME}.service"));
    fs::write(&path, unit).with_context(|| {
        format!(
            "write {} (need root). Alternatively write user unit under ~/.config/systemd/user/",
            path.display()
        )
    })?;
    let _ = Command::new("systemctl").args(["daemon-reload"]).output();
    let _ = Command::new("systemctl")
        .args(["enable", SERVICE_NAME])
        .output();
    Ok(format!(
        "systemd unit installed at {}. Start: systemctl start {SERVICE_NAME}",
        path.display()
    ))
}

fn uninstall_systemd() -> Result<String> {
    let _ = Command::new("systemctl")
        .args(["disable", "--now", SERVICE_NAME])
        .output();
    let path = PathBuf::from(format!("/etc/systemd/system/{SERVICE_NAME}.service"));
    if path.is_file() {
        fs::remove_file(&path)?;
        let _ = Command::new("systemctl").args(["daemon-reload"]).output();
    }
    Ok(format!("systemd unit '{SERVICE_NAME}' removed"))
}

fn status_systemd() -> Result<ServiceStatus> {
    let out = Command::new("systemctl")
        .args(["status", SERVICE_NAME, "--no-pager"])
        .output()
        .map_err(|e| anyhow!("systemctl: {e}"))?;
    let detail = String::from_utf8_lossy(&out.stdout).to_string()
        + &String::from_utf8_lossy(&out.stderr);
    let path = PathBuf::from(format!("/etc/systemd/system/{SERVICE_NAME}.service"));
    Ok(ServiceStatus {
        kind: "systemd".into(),
        name: SERVICE_NAME.into(),
        installed: path.is_file() || out.status.success(),
        detail,
    })
}
