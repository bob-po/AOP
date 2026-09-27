use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;

use anyhow::{anyhow, Context, Result};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::logs::LogHub;

#[derive(Debug, Clone)]
pub struct SpawnSpec {
    pub id: String,
    pub command: String,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
    pub workdir: Option<PathBuf>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ChildHandle {
    pub id: String,
    pub pid: u32,
    pub command: String,
    pub args: Vec<String>,
    pub running: bool,
}

struct ManagedChild {
    spec: SpawnSpec,
    child: Child,
    pid: u32,
}

/// Spawns children with piped stdio → LogHub; tracks PIDs for kill.
pub struct ProcessManager {
    children: Mutex<HashMap<String, ManagedChild>>,
    logs: LogHub,
}

impl ProcessManager {
    pub fn new(logs: LogHub) -> Arc<Self> {
        Arc::new(Self {
            children: Mutex::new(HashMap::new()),
            logs,
        })
    }

    pub async fn list(&self) -> Vec<ChildHandle> {
        let mut out = Vec::new();
        let mut map = self.children.lock().await;
        let mut dead = Vec::new();
        for (id, mc) in map.iter_mut() {
            let running = match mc.child.try_wait() {
                Ok(None) => true,
                Ok(Some(_)) => false,
                Err(_) => false,
            };
            if !running {
                dead.push(id.clone());
            }
            out.push(ChildHandle {
                id: id.clone(),
                pid: mc.pid,
                command: mc.spec.command.clone(),
                args: mc.spec.args.clone(),
                running,
            });
        }
        for id in dead {
            map.remove(&id);
        }
        out
    }

    pub async fn get(&self, id: &str) -> Option<ChildHandle> {
        self.list().await.into_iter().find(|c| c.id == id)
    }

    pub async fn spawn(self: &Arc<Self>, spec: SpawnSpec) -> Result<ChildHandle> {
        {
            let mut map = self.children.lock().await;
            if let Some(existing) = map.get_mut(&spec.id) {
                if let Ok(None) = existing.child.try_wait() {
                    return Err(anyhow!("process {} already running (pid {})", spec.id, existing.pid));
                }
            }
        }

        let mut cmd = Command::new(&spec.command);
        cmd.args(&spec.args)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        if let Some(wd) = &spec.workdir {
            cmd.current_dir(wd);
        }
        for (k, v) in &spec.env {
            cmd.env(k, v);
        }

        // New process group on Unix so we can kill the tree.
        #[cfg(unix)]
        {
            #[allow(unused_imports)]
            use std::os::unix::process::CommandExt;
            // tokio::process::Command doesn't expose pre_exec easily on all versions;
            // rely on kill_on_drop + explicit kill.
        }

        let mut child = cmd
            .spawn()
            .with_context(|| format!("spawn {} ({})", spec.id, spec.command))?;
        let pid = child.id().unwrap_or(0);

        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        let logs = self.logs.clone();
        let id_out = spec.id.clone();
        let id_err = spec.id.clone();

        if let Some(out) = stdout {
            tokio::spawn(async move {
                let mut lines = BufReader::new(out).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = logs.append(&id_out, &format!("[stdout] {line}"));
                }
            });
        }
        let logs2 = self.logs.clone();
        if let Some(err) = stderr {
            tokio::spawn(async move {
                let mut lines = BufReader::new(err).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = logs2.append(&id_err, &format!("[stderr] {line}"));
                }
            });
        }

        let _ = self.logs.append(
            &spec.id,
            &format!("[sys] started pid={pid} cmd={} {:?}", spec.command, spec.args),
        );

        let handle = ChildHandle {
            id: spec.id.clone(),
            pid,
            command: spec.command.clone(),
            args: spec.args.clone(),
            running: true,
        };

        let mut map = self.children.lock().await;
        map.insert(
            spec.id.clone(),
            ManagedChild {
                spec,
                child,
                pid,
            },
        );
        info!(pid, id = %handle.id, "child spawned");
        Ok(handle)
    }

    pub async fn kill(&self, id: &str) -> Result<()> {
        let mut map = self.children.lock().await;
        let Some(mut mc) = map.remove(id) else {
            return Err(anyhow!("no managed process {id}"));
        };
        let pid = mc.pid;
        match mc.child.start_kill() {
            Ok(()) => {
                let _ = mc.child.wait().await;
                let _ = self.logs.append(id, &format!("[sys] killed pid={pid}"));
                info!(pid, id, "child killed");
                Ok(())
            }
            Err(e) => {
                warn!(pid, id, error = %e, "kill failed");
                Err(e.into())
            }
        }
    }

    pub async fn kill_all(&self) {
        let ids: Vec<String> = {
            let map = self.children.lock().await;
            map.keys().cloned().collect()
        };
        for id in ids {
            if let Err(e) = self.kill(&id).await {
                warn!(id, error = %e, "kill_all entry failed");
            }
        }
    }
}
