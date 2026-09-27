//! Self-update skeleton: fetch manifest → sha256 check → stage binary.

use std::env;
use std::fs;
use std::path::PathBuf;

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tracing::info;

use aop_core::CLIENT_VERSION;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpdateManifest {
    pub version: String,
    pub url: String,
    pub sha256: String,
    #[serde(default)]
    pub notes: String,
}

#[derive(Debug, Serialize)]
pub struct UpdateStatus {
    pub current_version: String,
    pub update_available: bool,
    pub remote_version: Option<String>,
    pub applied: bool,
    pub message: String,
}

pub async fn check_and_apply_update(
    manifest_url: &str,
    apply: bool,
) -> Result<UpdateStatus> {
    if manifest_url.trim().is_empty() {
        return Ok(UpdateStatus {
            current_version: CLIENT_VERSION.into(),
            update_available: false,
            remote_version: None,
            applied: false,
            message: "update_manifest_url empty; self-update disabled".into(),
        });
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()?;
    let manifest: UpdateManifest = client
        .get(manifest_url)
        .send()
        .await
        .context("fetch update manifest")?
        .error_for_status()
        .context("manifest HTTP error")?
        .json()
        .await
        .context("parse update manifest")?;

    if manifest.version == CLIENT_VERSION {
        return Ok(UpdateStatus {
            current_version: CLIENT_VERSION.into(),
            update_available: false,
            remote_version: Some(manifest.version),
            applied: false,
            message: "already on latest version".into(),
        });
    }

    if !apply {
        return Ok(UpdateStatus {
            current_version: CLIENT_VERSION.into(),
            update_available: true,
            remote_version: Some(manifest.version),
            applied: false,
            message: "update available (pass apply=true to download)".into(),
        });
    }

    let bytes = client
        .get(&manifest.url)
        .send()
        .await
        .context("download update")?
        .error_for_status()?
        .bytes()
        .await?;

    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let got = hex::encode(hasher.finalize());
    let expected = manifest.sha256.trim().to_ascii_lowercase();
    if got != expected {
        bail!("sha256 mismatch: got {got}, expected {expected}");
    }

    let exe = env::current_exe().context("current_exe")?;
    let dir = exe
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    let staged = dir.join(format!("aopd.new-{}", manifest.version));
    fs::write(&staged, &bytes).with_context(|| format!("write {}", staged.display()))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&staged)?.permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&staged, perms)?;
    }

    // Side-by-side replace: write sibling then note for restart.
    let replace_as = if cfg!(windows) {
        dir.join("aopd.exe.pending")
    } else {
        dir.join("aopd.pending")
    };
    fs::rename(&staged, &replace_as).or_else(|_| {
        fs::copy(&staged, &replace_as)?;
        fs::remove_file(&staged)?;
        Ok::<(), std::io::Error>(())
    })?;

    info!(version = %manifest.version, path = %replace_as.display(), "update staged");
    Ok(UpdateStatus {
        current_version: CLIENT_VERSION.into(),
        update_available: true,
        remote_version: Some(manifest.version.clone()),
        applied: true,
        message: format!(
            "staged {} — restart service to swap in pending binary",
            replace_as.display()
        ),
    })
}
