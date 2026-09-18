package httpapi

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
)

type RBACHandlers struct {
	Store  *auth.Store
	AuthOn bool
}

func (h *RBACHandlers) Routes(r chi.Router) {
	r.Get("/roles", h.listRoles)
	r.Get("/me", h.me)
}

func (h *RBACHandlers) listRoles(w http.ResponseWriter, r *http.Request) {
	roles := make([]map[string]any, 0, len(auth.RoleNames()))
	for _, name := range auth.RoleNames() {
		roles = append(roles, map[string]any{
			"role":   name,
			"scopes": auth.RoleCatalog[name],
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"roles": roles,
		"docs":  "Assign role:<name> or bare role name on api_keys.scopes; expanded at auth time.",
	})
}

func (h *RBACHandlers) me(w http.ResponseWriter, r *http.Request) {
	p, ok := PrincipalFromContext(r.Context())
	if !ok {
		if !h.AuthOn {
			writeJSON(w, http.StatusOK, map[string]any{
				"authenticated": false,
				"auth_required": false,
				"scopes":        []string{"*"},
				"roles":         []string{"admin"},
				"expanded":      []string{"*"},
			})
			return
		}
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing principal", nil)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"authenticated": true,
		"auth_required": h.AuthOn,
		"api_key_id":    p.APIKeyID,
		"tenant_id":     p.TenantID,
		"name":          p.Name,
		"scopes":        p.Scopes,
		"roles":         auth.RolesOf(p.Scopes),
		"expanded":      auth.ExpandScopes(p.Scopes),
	})
}
