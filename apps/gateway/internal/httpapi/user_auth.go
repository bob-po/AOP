package httpapi

import (
	"encoding/json"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
)

type AuthHandlers struct {
	Store  *auth.Store
	Audit  *auth.AuditStore
	Tenant string
	AuthOn bool
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (h *AuthHandlers) Routes(r chi.Router) {
	r.Post("/login", h.login)
	r.Post("/logout", h.logout)
	r.Get("/me", h.me)
}

func sessionTTL() time.Duration {
	hours, _ := strconv.Atoi(strings.TrimSpace(os.Getenv("AUTH_SESSION_HOURS")))
	if hours <= 0 {
		hours = 24
	}
	return time.Duration(hours) * time.Hour
}

func (h *AuthHandlers) login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "validation_error", "invalid json body", nil)
		return
	}
	email := strings.TrimSpace(req.Email)
	if email == "" || req.Password == "" {
		writeError(w, http.StatusBadRequest, "validation_error", "email and password required", nil)
		return
	}
	tenant := h.Tenant
	user, hash, err := h.Store.FindUserByEmail(r.Context(), tenant, email)
	if err != nil || !auth.CheckPassword(hash, req.Password) {
		writeError(w, http.StatusUnauthorized, "unauthorized", "invalid credentials", nil)
		return
	}
	token, expires, err := h.Store.CreateSession(r.Context(), user, sessionTTL())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to create session", err.Error())
		return
	}
	recordAudit(h.Audit, r, tenant, "auth.login", "user", user.ID, map[string]any{
		"email": user.Email,
		"role":  user.Role,
	})
	writeJSON(w, http.StatusOK, map[string]any{
		"token":         token,
		"token_type":    "Bearer",
		"expires_at":    expires.UTC().Format(time.RFC3339),
		"user": map[string]any{
			"id":           user.ID,
			"email":        user.Email,
			"display_name": user.DisplayName,
			"role":         user.Role,
			"tenant_id":    user.TenantID,
		},
		"scopes": auth.ExpandScopes(auth.ScopesForUserRole(user.Role)),
	})
}

func (h *AuthHandlers) logout(w http.ResponseWriter, r *http.Request) {
	raw := bearerToken(r)
	if strings.HasPrefix(raw, "aop_sess_") {
		_ = h.Store.RevokeSession(r.Context(), raw)
		if p, ok := PrincipalFromContext(r.Context()); ok {
			recordAudit(h.Audit, r, p.TenantID, "auth.logout", "user", p.UserID, nil)
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"logged_out": true})
}

func (h *AuthHandlers) me(w http.ResponseWriter, r *http.Request) {
	p, ok := PrincipalFromContext(r.Context())
	if !ok {
		if !h.AuthOn {
			writeJSON(w, http.StatusOK, map[string]any{
				"authenticated": false,
				"auth_required": false,
				"kind":          "anonymous",
			})
			return
		}
		writeError(w, http.StatusUnauthorized, "unauthorized", "not authenticated", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"authenticated": true,
		"auth_required": h.AuthOn,
		"kind":          p.Kind,
		"api_key_id":    p.APIKeyID,
		"session_id":    p.SessionID,
		"user_id":       p.UserID,
		"email":         p.Email,
		"name":          p.Name,
		"user_role":     p.UserRole,
		"tenant_id":     p.TenantID,
		"scopes":        p.Scopes,
		"expanded":      auth.ExpandScopes(p.Scopes),
		"roles":         auth.RolesOf(p.Scopes),
	})
}
