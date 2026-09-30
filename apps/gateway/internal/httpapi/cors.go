package httpapi

import (
	"net/http"
	"os"
	"strings"
)

// withCORS applies an origin allowlist. Set CORS_ORIGINS to a comma-separated
// list (e.g. "http://localhost:3000,https://console.example.com").
// When unset, only common local-dev origins are reflected; credentials are
// never paired with "*".
func withCORS(next http.Handler) http.Handler {
	allowed := corsAllowedOrigins()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := strings.TrimSpace(r.Header.Get("Origin"))
		if origin != "" && corsOriginAllowed(origin, allowed) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Credentials", "true")
			w.Header().Set("Vary", "Origin")
		}
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Requested-With, X-Tenant-ID")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func corsAllowedOrigins() map[string]struct{} {
	raw := strings.TrimSpace(os.Getenv("CORS_ORIGINS"))
	out := map[string]struct{}{}
	if raw == "" {
		for _, o := range []string{
			"http://localhost:3000",
			"http://127.0.0.1:3000",
			"http://localhost:3001",
			"http://127.0.0.1:3001",
		} {
			out[o] = struct{}{}
		}
		return out
	}
	for _, part := range strings.Split(raw, ",") {
		o := strings.TrimSpace(part)
		if o != "" {
			out[o] = struct{}{}
		}
	}
	return out
}

func corsOriginAllowed(origin string, allowed map[string]struct{}) bool {
	_, ok := allowed[origin]
	return ok
}
