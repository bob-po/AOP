use std::path::{Path, PathBuf};

/// Expand `~` and optional env-style home for config paths.
pub fn expand_path(raw: impl AsRef<str>) -> PathBuf {
    let s = raw.as_ref().trim();
    if s.is_empty() {
        return PathBuf::new();
    }
    if s == "~" {
        return dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
    }
    if let Some(rest) = s.strip_prefix("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(rest);
        }
    }
    if let Some(rest) = s.strip_prefix("~\\") {
        if let Some(home) = dirs::home_dir() {
            return home.join(rest);
        }
    }
    PathBuf::from(s)
}

pub fn resolve_relative(base: &Path, raw: impl AsRef<str>) -> PathBuf {
    let p = expand_path(raw);
    if p.is_absolute() {
        p
    } else {
        base.join(p)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expand_plain() {
        assert_eq!(expand_path("foo/bar"), PathBuf::from("foo/bar"));
    }

    #[test]
    fn expand_tilde_home() {
        let p = expand_path("~/aop");
        assert!(p.to_string_lossy().contains("aop"));
        assert!(!p.to_string_lossy().starts_with('~'));
    }
}
