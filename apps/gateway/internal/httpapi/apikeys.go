package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
)

type APIKeyHandlers struct {
	Store   *auth.Store
	Audit   *auth.AuditStore
	Tenant  string
	AuthOn  bool
}

type createKeyRequest struct {
	Name   string   `json:"name"`
	Role   string   `json:"role"`
	Scopes []string `json:"scopes"`
}

func (h *APIKeyHandlers) Routes(r chi.Router) {
	r.Get("/", h.list)
	r.Post("/", h.create)
	r.Delete("/{keyID}", h.revoke)
}

func (h *APIKeyHandlers) list(w http.ResponseWriter, r *http.Request) {
	tenant := tenantOrDefault(r, h.Tenant)
	if !h.canManage(r) {
		writeError(w, http.StatusForbidden, "forbidden", "api key management requires admin scope or auth disabled", nil)
		return
	}
	items, err := h.Store.List(r.Context(), tenant)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list api keys", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"api_keys": items})
}

func (h *APIKeyHandlers) create(w http.ResponseWriter, r *http.Request) {
	tenant := tenantOrDefault(r, h.Tenant)
	if !h.canManage(r) {
		writeError(w, http.StatusForbidden, "forbidden", "api key management requires admin scope or auth disabled", nil)
		return
	}
	var req createKeyRequest
	_ = json.NewDecoder(r.Body).Decode(&req)
	scopes := req.Scopes
	if role := strings.TrimSpace(req.Role); role != "" {
		scopes = []string{"role:" + auth.NormalizeRole(role)}
	}
	rec, err := h.Store.Create(r.Context(), tenant, strings.TrimSpace(req.Name), scopes)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to create api key", err.Error())
		return
	}
	recordAudit(h.Audit, r, tenant, "api_key.create", "api_key", rec.ID, map[string]any{
		"name":   rec.Name,
		"scopes": rec.Scopes,
	})
	writeJSON(w, http.StatusCreated, rec)
}

func (h *APIKeyHandlers) revoke(w http.ResponseWriter, r *http.Request) {
	tenant := tenantOrDefault(r, h.Tenant)
	if !h.canManage(r) {
		writeError(w, http.StatusForbidden, "forbidden", "api key management requires admin scope or auth disabled", nil)
		return
	}
	keyID := chi.URLParam(r, "keyID")
	if err := h.Store.Revoke(r.Context(), tenant, keyID); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error(), nil)
		return
	}
	recordAudit(h.Audit, r, tenant, "api_key.revoke", "api_key", keyID, nil)
	writeJSON(w, http.StatusOK, map[string]any{"revoked": true, "id": keyID})
}

func (h *APIKeyHandlers) canManage(r *http.Request) bool {
	if !h.AuthOn {
		return true
	}
	p, ok := PrincipalFromContext(r.Context())
	if !ok {
		return false
	}
	return h.Store.HasScope(p, "admin") || h.Store.HasScope(p, "api_key.admin")
}
