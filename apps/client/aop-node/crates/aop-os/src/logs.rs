use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result};

/// Append-only log files under `log_dir/<id>.log`.
#[derive(Clone)]
pub struct LogHub {
    root: PathBuf,
    writers: Arc<Mutex<HashMap<String, File>>>,
}

impl LogHub {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self> {
        let root = root.into();
        fs::create_dir_all(&root)
            .with_context(|| format!("create log dir {}", root.display()))?;
        Ok(Self {
            root,
            writers: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    pub fn path_for(&self, id: &str) -> PathBuf {
        self.root.join(format!("{id}.log"))
    }

    pub fn append(&self, id: &str, line: &str) -> Result<()> {
        let mut map = self.writers.lock().expect("log writers");
        if !map.contains_key(id) {
            let path = self.path_for(id);
            let f = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)
                .with_context(|| format!("open log {}", path.display()))?;
            map.insert(id.to_string(), f);
        }
        let f = map.get_mut(id).expect("writer");
        writeln!(f, "{line}")?;
        f.flush()?;
        Ok(())
    }
}

/// Read the last `max_bytes` from a log file.
pub fn read_log_tail(path: impl AsRef<Path>, max_bytes: u64) -> Result<String> {
    let path = path.as_ref();
    if !path.is_file() {
        return Ok(String::new());
    }
    let mut f = File::open(path)?;
    let len = f.metadata()?.len();
    let start = len.saturating_sub(max_bytes);
    f.seek(SeekFrom::Start(start))?;
    let mut buf = String::new();
    f.read_to_string(&mut buf)?;
    if start > 0 {
        // Drop partial first line
        if let Some(idx) = buf.find('\n') {
            return Ok(buf[idx + 1..].to_string());
        }
    }
    Ok(buf)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn append_and_tail() {
        let dir = tempdir().unwrap();
        let hub = LogHub::new(dir.path()).unwrap();
        hub.append("echo", "line1").unwrap();
        hub.append("echo", "line2").unwrap();
        let text = read_log_tail(hub.path_for("echo"), 4096).unwrap();
        assert!(text.contains("line1"));
        assert!(text.contains("line2"));
    }
}
