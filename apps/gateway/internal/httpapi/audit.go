package httpapi

import (
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
)

type AuditHandlers struct {
	Store  *auth.AuditStore
	Auth   *auth.Store
	Tenant string
	AuthOn bool
}

func (h *AuditHandlers) Routes(r chi.Router) {
	r.Get("/", h.list)
}

func (h *AuditHandlers) list(w http.ResponseWriter, r *http.Request) {
	if h.AuthOn {
		p, ok := PrincipalFromContext(r.Context())
		if !ok || (!h.Auth.HasScope(p, "admin") && !h.Auth.HasScope(p, "api_key.admin") && !h.Auth.HasScope(p, "audit.read")) {
			writeError(w, http.StatusForbidden, "forbidden", "audit list requires admin or audit.read", nil)
			return
		}
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	tenant := tenantOrDefault(r, h.Tenant)
	items, err := h.Store.List(r.Context(), tenant, limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list audit logs", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"audit_logs": items})
}

// recordAudit is best-effort; never fails the primary request.
func recordAudit(store *auth.AuditStore, r *http.Request, tenant, action, resourceType, resourceID string, extra map[string]any) {
	if store == nil {
		return
	}
	payload := map[string]any{}
	for k, v := range extra {
		payload[k] = v
	}
	if p, ok := PrincipalFromContext(r.Context()); ok {
		payload["api_key_id"] = p.APIKeyID
		payload["api_key_name"] = p.Name
	}
	_ = store.Append(r.Context(), tenant, action, resourceType, resourceID, clientIP(r), payload)
}

func clientIP(r *http.Request) string {
	if xff := r.Header.Get("X-Real-IP"); xff != "" {
		return xff
	}
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		return xff
	}
	return r.RemoteAddr
}
