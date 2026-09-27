use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::config::WhitelistConfig;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecRequest {
    /// Registered agent/plugin id (preferred path).
    #[serde(default)]
    pub plugin_id: Option<String>,
    /// Raw argv; argv[0] must be an allowed binary basename or absolute path.
    #[serde(default)]
    pub argv: Vec<String>,
    #[serde(default)]
    pub workdir: Option<String>,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum WhitelistError {
    #[error("empty exec request")]
    Empty,
    #[error("plugin id not allowlisted: {0}")]
    PluginDenied(String),
    #[error("binary not allowlisted: {0}")]
    BinaryDenied(String),
    #[error("shell metacharacters are not allowed")]
    ShellMeta,
}

#[derive(Debug, Clone)]
pub struct Whitelist {
    allowed_binaries: Vec<String>,
    allowed_plugin_ids: Vec<String>,
    allowed_path_prefixes: Vec<PathBuf>,
}

impl Whitelist {
    pub fn from_config(cfg: &WhitelistConfig) -> Self {
        Self {
            allowed_binaries: cfg
                .allowed_binaries
                .iter()
                .map(|s| s.to_ascii_lowercase())
                .collect(),
            allowed_plugin_ids: cfg.allowed_plugin_ids.clone(),
            allowed_path_prefixes: cfg
                .allowed_path_prefixes
                .iter()
                .map(|p| PathBuf::from(p))
                .collect(),
        }
    }

    pub fn allows_plugin(&self, id: &str) -> bool {
        self.allowed_plugin_ids.iter().any(|x| x == id)
    }

    pub fn check(&self, req: &ExecRequest) -> Result<(), WhitelistError> {
        if let Some(id) = req.plugin_id.as_deref() {
            if id.is_empty() {
                return Err(WhitelistError::Empty);
            }
            if !self.allows_plugin(id) {
                return Err(WhitelistError::PluginDenied(id.to_string()));
            }
            // Plugin id path is enough; argv optional for supervisor-owned manifests.
            if req.argv.is_empty() {
                return Ok(());
            }
        }

        if req.argv.is_empty() && req.plugin_id.is_none() {
            return Err(WhitelistError::Empty);
        }

        for part in &req.argv {
            if contains_shell_meta(part) {
                return Err(WhitelistError::ShellMeta);
            }
        }

        if let Some(bin) = req.argv.first() {
            self.check_binary(bin)?;
        }
        Ok(())
    }

    fn check_binary(&self, bin: &str) -> Result<(), WhitelistError> {
        let path = Path::new(bin);
        let name = path
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or(bin)
            .to_ascii_lowercase();
        // Strip .exe on Windows-style names
        let stem = name.strip_suffix(".exe").unwrap_or(&name);

        if self.allowed_binaries.iter().any(|b| b == stem || b == &name) {
            return Ok(());
        }

        if path.is_absolute() {
            for prefix in &self.allowed_path_prefixes {
                if path.starts_with(prefix) {
                    return Ok(());
                }
            }
        }

        Err(WhitelistError::BinaryDenied(bin.to_string()))
    }
}

fn contains_shell_meta(s: &str) -> bool {
    s.chars().any(|c| matches!(c, '|' | '&' | ';' | '`' | '\n' | '\r'))
        || s.contains("$(")
        || s.contains("${")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::WhitelistConfig;

    fn wl() -> Whitelist {
        Whitelist::from_config(&WhitelistConfig {
            allowed_binaries: vec!["python".into(), "echo".into()],
            allowed_plugin_ids: vec!["echo".into(), "claude-code".into()],
            allowed_path_prefixes: vec!["C:\\tools".into()],
        })
    }

    #[test]
    fn allows_plugin_id() {
        let req = ExecRequest {
            plugin_id: Some("echo".into()),
            argv: vec![],
            workdir: None,
        };
        assert!(wl().check(&req).is_ok());
    }

    #[test]
    fn denies_unknown_plugin() {
        let req = ExecRequest {
            plugin_id: Some("evil".into()),
            argv: vec![],
            workdir: None,
        };
        assert_eq!(
            wl().check(&req).unwrap_err(),
            WhitelistError::PluginDenied("evil".into())
        );
    }

    #[test]
    fn allows_python_binary() {
        let req = ExecRequest {
            plugin_id: None,
            argv: vec!["python".into(), "-c".into(), "print(1)".into()],
            workdir: None,
        };
        assert!(wl().check(&req).is_ok());
    }

    #[test]
    fn denies_shell_meta() {
        let req = ExecRequest {
            plugin_id: None,
            argv: vec!["python".into(), "-c".into(), "x; rm -rf /".into()],
            workdir: None,
        };
        assert_eq!(wl().check(&req).unwrap_err(), WhitelistError::ShellMeta);
    }

    #[test]
    fn denies_unknown_binary() {
        let req = ExecRequest {
            plugin_id: None,
            argv: vec!["curl".into(), "http://x".into()],
            workdir: None,
        };
        assert!(matches!(
            wl().check(&req).unwrap_err(),
            WhitelistError::BinaryDenied(_)
        ));
    }
}
