use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::{Context, Result};
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};
use tower_http::cors::{Any, CorsLayer};
use tracing::info;

use aop_core::ExecRequest;
use aop_os::{check_and_apply_update, install_service, service_status, uninstall_service};

use crate::lifecycle::Supervisor;

#[derive(Clone)]
struct AppState {
    sup: Arc<Supervisor>,
    config_path: String,
}

pub async fn serve_mgmt(sup: Arc<Supervisor>, config_path: String) -> Result<()> {
    let addr: SocketAddr = sup
        .cfg
        .mgmt_listen
        .parse()
        .with_context(|| format!("invalid mgmt_listen {}", sup.cfg.mgmt_listen))?;

    // Loopback only guard
    if !addr.ip().is_loopback() {
        anyhow::bail!(
            "mgmt_listen must be loopback (127.0.0.1 / ::1), got {}",
            addr.ip()
        );
    }

    let state = AppState { sup, config_path };
    let app = Router::new()
        .route("/health", get(health))
        .route("/.well-known/agent-card.json", get(agent_card))
        .route("/.well-known/agent.json", get(agent_card))
        .route("/v1/status", get(status))
        .route("/v1/agents", get(list_agents))
        .route("/v1/agents/:id/start", post(start_agent))
        .route("/v1/agents/:id/stop", post(stop_agent))
        .route("/v1/agents/:id/restart", post(restart_agent))
        .route("/v1/logs/:id", get(logs))
        .route("/v1/exec", post(exec))
        .route("/v1/service/install", post(svc_install))
        .route("/v1/service/uninstall", post(svc_uninstall))
        .route("/v1/service/status", get(svc_status))
        .route("/v1/update", post(update))
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .with_state(state);

    info!(%addr, "mgmt HTTP listening");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health(State(st): State<AppState>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "service": "aopd",
        "node_id": st.sup.cfg.node_id,
        "runner_ready": true,
        "client_version": aop_core::CLIENT_VERSION,
    }))
}

async fn agent_card(State(st): State<AppState>) -> Json<Value> {
    let endpoint = st.sup.cfg.register_endpoint.trim_end_matches('/').to_string() + "/";
    Json(json!({
        "name": format!("AOP Node {}", st.sup.cfg.node_id),
        "description": "AOP Node Supervisor — manages local harness agents/plugins",
        "url": endpoint,
        "version": aop_core::CLIENT_VERSION,
        "protocolVersion": "0.3.0",
        "preferredTransport": "JSONRPC",
        "capabilities": { "streaming": false, "pushNotifications": false },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["application/json"],
        "skills": [],
        "securitySchemes": {},
        "security": [],
        "supportsAuthenticatedExtendedCard": false,
        "extensions": [],
        "provider": { "organization": "AOP", "url": "https://github.com/aop-platform/aop" }
    }))
}

async fn status(State(st): State<AppState>) -> Json<Value> {
    Json(serde_json::to_value(st.sup.status().await).unwrap_or(json!({})))
}

async fn list_agents(State(st): State<AppState>) -> Json<Value> {
    let snap = st.sup.status().await;
    Json(json!({"agents": snap.children}))
}

async fn start_agent(
    State(st): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    st.sup
        .start_child(&id)
        .await
        .map(|h| Json(json!(h)))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

async fn stop_agent(
    State(st): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    st.sup
        .stop_child(&id)
        .await
        .map(|_| Json(json!({"ok": true, "id": id})))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

async fn restart_agent(
    State(st): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, String)> {
    st.sup
        .restart_child(&id)
        .await
        .map(|h| Json(json!(h)))
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))
}

#[derive(Deserialize)]
struct LogsQuery {
    #[serde(default = "default_log_bytes")]
    max_bytes: u64,
}

fn default_log_bytes() -> u64 {
    64 * 1024
}

async fn logs(
    State(st): State<AppState>,
    Path(id): Path<String>,
    Query(q): Query<LogsQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    st.sup
        .read_logs(&id, q.max_bytes)
        .map(|text| Json(json!({"id": id, "text": text})))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn exec(
    State(st): State<AppState>,
    Json(req): Json<ExecRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    st.sup
        .exec_whitelisted(req)
        .await
        .map(|h| Json(json!(h)))
        .map_err(|e| (StatusCode::FORBIDDEN, e.to_string()))
}

async fn svc_install(
    State(st): State<AppState>,
) -> Result<Json<Value>, (StatusCode, String)> {
    install_service(&st.config_path)
        .map(|msg| Json(json!({"ok": true, "message": msg})))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn svc_uninstall() -> Result<Json<Value>, (StatusCode, String)> {
    uninstall_service()
        .map(|msg| Json(json!({"ok": true, "message": msg})))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

async fn svc_status() -> Result<Json<Value>, (StatusCode, String)> {
    service_status()
        .map(|s| Json(json!(s)))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

#[derive(Deserialize)]
struct UpdateBody {
    #[serde(default)]
    apply: bool,
}

async fn update(
    State(st): State<AppState>,
    Json(body): Json<UpdateBody>,
) -> Result<Json<Value>, (StatusCode, String)> {
    check_and_apply_update(&st.sup.cfg.update_manifest_url, body.apply)
        .await
        .map(|s| Json(json!(s)))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}
