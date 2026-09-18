package auth

import "testing"

func TestExpandScopesRoles(t *testing.T) {
	got := ExpandScopes([]string{"role:viewer", "task.write"})
	want := map[string]bool{"task.read": true, "agent.read": true, "memory.read": true, "task.write": true}
	for _, sc := range got {
		if !want[sc] {
			t.Fatalf("unexpected scope %s in %v", sc, got)
		}
		delete(want, sc)
	}
	if len(want) != 0 {
		t.Fatalf("missing scopes %v", want)
	}
}

func TestHasScopeWithRole(t *testing.T) {
	s := &Store{}
	p := Principal{Scopes: []string{"role:operator"}}
	if !s.HasScope(p, "task.write") {
		t.Fatal("operator should have task.write")
	}
	if !s.HasScope(p, "agent.write") {
		t.Fatal("operator should have agent.write")
	}
	viewer := Principal{Scopes: []string{"viewer"}}
	if viewerHas := s.HasScope(viewer, "task.write"); viewerHas {
		t.Fatal("viewer must not have task.write")
	}
	if !s.HasScope(viewer, "task.read") {
		t.Fatal("viewer should have task.read")
	}
}

func TestRolesOf(t *testing.T) {
	roles := RolesOf([]string{"role:admin", "task.read"})
	if len(roles) != 1 || roles[0] != "admin" {
		t.Fatalf("got %v", roles)
	}
}
