use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use serde_json::Value;

use aop_core::{Config, DEFAULT_MGMT_LISTEN, ExecRequest};
use aop_os::{install_service, service_status, uninstall_service};

#[derive(Parser, Debug)]
#[command(name = "aop", version, about = "AOP Node local management CLI")]
struct Args {
    /// aopd management base URL
    #[arg(long, env = "AOP_MGMT_URL", default_value_t = format!("http://{DEFAULT_MGMT_LISTEN}"))]
    mgmt: String,

    /// Config path (for service install / offline helpers)
    #[arg(short, long, env = "AOP_NODE_CONFIG", default_value = "aop-node.toml")]
    config: PathBuf,

    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Show daemon status
    Status,
    /// List managed child agents/plugins
    Agents,
    /// Tail logs for an id
    Logs {
        id: String,
        #[arg(long, default_value_t = 65536)]
        max_bytes: u64,
    },
    /// Start a planned agent/plugin
    Start { id: String },
    /// Stop a running child
    Stop { id: String },
    /// Restart a child
    Restart { id: String },
    /// Whitelisted exec (plugin_id and/or argv)
    Exec {
        #[arg(long)]
        plugin_id: Option<String>,
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        argv: Vec<String>,
    },
    /// OS service helpers (do not require aopd for install)
    Service {
        #[command(subcommand)]
        action: ServiceCmd,
    },
    /// Check / apply self-update via daemon
    Update {
        #[arg(long, default_value_t = false)]
        apply: bool,
    },
    /// Print resolved config (local file)
    Config,
}

#[derive(Subcommand, Debug)]
enum ServiceCmd {
    Install,
    Uninstall,
    Status,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let base = args.mgmt.trim_end_matches('/').to_string();
    let http = reqwest::Client::new();

    match args.cmd {
        Cmd::Status => {
            let v = get_json(&http, &format!("{base}/v1/status")).await?;
            println!("{}", pretty(&v));
        }
        Cmd::Agents => {
            let v = get_json(&http, &format!("{base}/v1/agents")).await?;
            println!("{}", pretty(&v));
        }
        Cmd::Logs { id, max_bytes } => {
            let url = format!("{base}/v1/logs/{id}?max_bytes={max_bytes}");
            let v = get_json(&http, &url).await?;
            if let Some(text) = v.get("text").and_then(|t| t.as_str()) {
                print!("{text}");
            } else {
                println!("{}", pretty(&v));
            }
        }
        Cmd::Start { id } => {
            let v = post_json(&http, &format!("{base}/v1/agents/{id}/start"), &Value::Null).await?;
            println!("{}", pretty(&v));
        }
        Cmd::Stop { id } => {
            let v = post_json(&http, &format!("{base}/v1/agents/{id}/stop"), &Value::Null).await?;
            println!("{}", pretty(&v));
        }
        Cmd::Restart { id } => {
            let v =
                post_json(&http, &format!("{base}/v1/agents/{id}/restart"), &Value::Null).await?;
            println!("{}", pretty(&v));
        }
        Cmd::Exec { plugin_id, argv } => {
            let body = ExecRequest {
                plugin_id,
                argv,
                workdir: None,
            };
            let v = post_json(
                &http,
                &format!("{base}/v1/exec"),
                &serde_json::to_value(body)?,
            )
            .await?;
            println!("{}", pretty(&v));
        }
        Cmd::Service { action } => match action {
            ServiceCmd::Install => {
                let cfg = args
                    .config
                    .canonicalize()
                    .unwrap_or_else(|_| args.config.clone());
                let msg = install_service(&cfg.to_string_lossy())?;
                println!("{msg}");
            }
            ServiceCmd::Uninstall => {
                println!("{}", uninstall_service()?);
            }
            ServiceCmd::Status => {
                // Prefer daemon if up, else local sc/systemctl
                match get_json(&http, &format!("{base}/v1/service/status")).await {
                    Ok(v) => println!("{}", pretty(&v)),
                    Err(_) => {
                        let s = service_status()?;
                        println!("{}", pretty(&serde_json::to_value(s)?));
                    }
                }
            }
        },
        Cmd::Update { apply } => {
            let v = post_json(
                &http,
                &format!("{base}/v1/update"),
                &serde_json::json!({"apply": apply}),
            )
            .await?;
            println!("{}", pretty(&v));
        }
        Cmd::Config => {
            let cfg = if args.config.is_file() {
                Config::load(&args.config)?
            } else {
                Config::example()
            };
            println!("{}", pretty(&serde_json::to_value(cfg)?));
        }
    }
    Ok(())
}

fn pretty(v: &Value) -> String {
    serde_json::to_string_pretty(v).unwrap_or_else(|_| v.to_string())
}

async fn get_json(http: &reqwest::Client, url: &str) -> Result<Value> {
    let resp = http.get(url).send().await.with_context(|| format!("GET {url}"))?;
    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();
    if !status.is_success() {
        anyhow::bail!("{url} -> {status}: {text}");
    }
    Ok(serde_json::from_str(&text).unwrap_or(serde_json::json!({"raw": text})))
}

async fn post_json(http: &reqwest::Client, url: &str, body: &Value) -> Result<Value> {
    let resp = http
        .post(url)
        .json(body)
        .send()
        .await
        .with_context(|| format!("POST {url}"))?;
    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();
    if !status.is_success() {
        anyhow::bail!("{url} -> {status}: {text}");
    }
    Ok(serde_json::from_str(&text).unwrap_or(serde_json::json!({"raw": text})))
}
