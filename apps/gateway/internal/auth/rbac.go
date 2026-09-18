package auth

import "strings"

// Built-in roles (Phase 23). Stored on api_keys.scopes as "role:<name>" or bare name.
var RoleCatalog = map[string][]string{
	"viewer": {
		"task.read",
		"agent.read",
		"memory.read",
	},
	"operator": {
		"task.read",
		"task.write",
		"agent.read",
		"agent.write",
		"memory.read",
		"memory.write",
	},
	"admin": {
		"*",
	},
}

// RoleNames returns sorted role ids for API listing.
func RoleNames() []string {
	return []string{"viewer", "operator", "admin"}
}

func NormalizeRole(name string) string {
	name = strings.TrimSpace(strings.ToLower(name))
	name = strings.TrimPrefix(name, "role:")
	return name
}

// ExpandScopes turns role tokens into concrete scopes (roles kept as-is for display).
func ExpandScopes(scopes []string) []string {
	out := make([]string, 0, len(scopes)*4)
	seen := map[string]struct{}{}
	add := func(s string) {
		s = strings.TrimSpace(s)
		if s == "" {
			return
		}
		if _, ok := seen[s]; ok {
			return
		}
		seen[s] = struct{}{}
		out = append(out, s)
	}
	for _, sc := range scopes {
		sc = strings.TrimSpace(sc)
		role := NormalizeRole(sc)
		if expanded, ok := RoleCatalog[role]; ok && (sc == role || strings.HasPrefix(sc, "role:")) {
			for _, e := range expanded {
				add(e)
			}
			continue
		}
		add(sc)
	}
	return out
}

func RolesOf(scopes []string) []string {
	roles := make([]string, 0)
	seen := map[string]struct{}{}
	for _, sc := range scopes {
		role := NormalizeRole(sc)
		if _, ok := RoleCatalog[role]; ok && (sc == role || strings.HasPrefix(strings.TrimSpace(sc), "role:")) {
			if _, dup := seen[role]; !dup {
				seen[role] = struct{}{}
				roles = append(roles, role)
			}
		}
	}
	return roles
}
