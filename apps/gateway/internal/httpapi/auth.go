package httpapi

import (
	"context"
	"net/http"
	"strings"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
)

type ctxKey string

const principalKey ctxKey = "principal"

func PrincipalFromContext(ctx context.Context) (auth.Principal, bool) {
	p, ok := ctx.Value(principalKey).(auth.Principal)
	return p, ok
}

func withAuth(store *auth.Store, required bool, defaultTenant string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method == http.MethodOptions {
				next.ServeHTTP(w, r)
				return
			}
			path := r.URL.Path
			// Public endpoints (Prometheus scrape + health probes + login + Stripe webhook)
			if path == "/" || path == "/health" || path == "/metrics" ||
				path == "/v1/auth/login" ||
				path == "/v1/billing/webhooks/stripe" {
				next.ServeHTTP(w, r)
				return
			}

			raw := bearerToken(r)
			if raw == "" {
				if required {
					writeError(w, http.StatusUnauthorized, "unauthorized", "missing Authorization Bearer token", nil)
					return
				}
				next.ServeHTTP(w, r)
				return
			}

			var p auth.Principal
			var err error
			if strings.HasPrefix(raw, "aop_sess_") {
				p, err = store.AuthenticateSession(r.Context(), raw)
			} else {
				p, err = store.Authenticate(r.Context(), raw)
			}
			if err != nil {
				writeError(w, http.StatusUnauthorized, "unauthorized", "invalid credentials", err.Error())
				return
			}
			ctx := context.WithValue(r.Context(), principalKey, p)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// requireScopeIfAuthed enforces scope when a principal is present (Phase 15).
// Anonymous local mode (AUTH_REQUIRED=false, no key) is allowed through.
func requireScopeIfAuthed(store *auth.Store, scope string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			p, ok := PrincipalFromContext(r.Context())
			if !ok {
				next.ServeHTTP(w, r)
				return
			}
			if !store.HasScope(p, scope) {
				writeError(w, http.StatusForbidden, "forbidden", "insufficient scope", map[string]string{"need": scope})
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// requireMutatingScope applies scope checks only to non-safe HTTP methods.
func requireMutatingScope(store *auth.Store, scope string) func(http.Handler) http.Handler {
	inner := requireScopeIfAuthed(store, scope)
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch r.Method {
			case http.MethodGet, http.MethodHead, http.MethodOptions:
				next.ServeHTTP(w, r)
				return
			default:
				inner(next).ServeHTTP(w, r)
			}
		})
	}
}

func requireScope(store *auth.Store, scope string) func(http.Handler) http.Handler {
	return requireScopeIfAuthed(store, scope)
}

func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if h != "" {
		parts := strings.SplitN(h, " ", 2)
		if len(parts) == 2 && strings.EqualFold(parts[0], "Bearer") {
			return strings.TrimSpace(parts[1])
		}
	}
	if key := strings.TrimSpace(r.Header.Get("X-API-Key")); key != "" {
		return key
	}
	if key := strings.TrimSpace(r.URL.Query().Get("api_key")); key != "" {
		return key
	}
	return ""
}

func tenantOrDefault(r *http.Request, fallback string) string {
	if p, ok := PrincipalFromContext(r.Context()); ok && p.TenantID != "" {
		return p.TenantID
	}
	return fallback
}
