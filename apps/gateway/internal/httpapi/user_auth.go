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
	r.Get("/users", h.listUsers)
	r.Post("/invite", h.invite)
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

type inviteRequest struct {
	Email        string `json:"email"`
	DisplayName  string `json:"display_name"`
	Role         string `json:"role"`
	WithAPIKey   bool   `json:"with_api_key"`
}

func (h *AuthHandlers) canInvite(r *http.Request) bool {
	if !h.AuthOn {
		return true
	}
	p, ok := PrincipalFromContext(r.Context())
	if !ok {
		return false
	}
	return h.Store.HasScope(p, "admin") || h.Store.HasScope(p, "api_key.admin")
}

func (h *AuthHandlers) listUsers(w http.ResponseWriter, r *http.Request) {
	if !h.canInvite(r) {
		writeError(w, http.StatusForbidden, "forbidden", "listing teammates requires admin", nil)
		return
	}
	tenant := tenantOrDefault(r, h.Tenant)
	users, err := h.Store.ListUsers(r.Context(), tenant)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list users", err.Error())
		return
	}
	items := make([]map[string]any, 0, len(users))
	for _, u := range users {
		items = append(items, map[string]any{
			"id":           u.ID,
			"email":        u.Email,
			"display_name": u.DisplayName,
			"role":         u.Role,
			"status":       u.Status,
			"tenant_id":    u.TenantID,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"users": items})
}

func (h *AuthHandlers) invite(w http.ResponseWriter, r *http.Request) {
	if !h.canInvite(r) {
		writeError(w, http.StatusForbidden, "forbidden", "invite requires admin", nil)
		return
	}
	var req inviteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "validation_error", "invalid json body", nil)
		return
	}
	tenant := tenantOrDefault(r, h.Tenant)
	password, err := auth.GenerateTempPassword()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate password", err.Error())
		return
	}
	user, err := h.Store.InviteUser(r.Context(), tenant, req.Email, req.DisplayName, req.Role, password)
	if err != nil {
		msg := err.Error()
		code := http.StatusBadRequest
		if strings.Contains(msg, "already exists") {
			code = http.StatusConflict
		}
		writeError(w, code, "invite_error", msg, nil)
		return
	}
	out := map[string]any{
		"user": map[string]any{
			"id":           user.ID,
			"email":        user.Email,
			"display_name": user.DisplayName,
			"role":         user.Role,
			"status":       user.Status,
			"tenant_id":    user.TenantID,
		},
		"temporary_password": password,
		"login_hint":         "Give them this email and temporary password once. They sign in at /login.",
	}
	if req.WithAPIKey {
		rec, kerr := h.Store.Create(r.Context(), tenant, "teammate:"+user.Email, []string{"role:" + auth.NormalizeRole(user.Role)})
		if kerr == nil {
			out["api_key"] = rec
		}
	}
	recordAudit(h.Audit, r, tenant, "auth.invite", "user", user.ID, map[string]any{
		"invited_email": user.Email,
		"role":          user.Role,
		"with_api_key":  req.WithAPIKey,
	})
	writeJSON(w, http.StatusCreated, out)
}
