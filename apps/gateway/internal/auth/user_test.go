package auth

import "testing"

func TestHashPasswordRoundTrip(t *testing.T) {
	hash, err := HashPassword("aop_admin_dev")
	if err != nil {
		t.Fatal(err)
	}
	if !CheckPassword(hash, "aop_admin_dev") {
		t.Fatal("password should match")
	}
	if CheckPassword(hash, "wrong") {
		t.Fatal("wrong password must fail")
	}
}

func TestScopesForUserRole(t *testing.T) {
	if got := ScopesForUserRole("admin"); len(got) != 1 || got[0] != "role:admin" {
		t.Fatalf("admin -> %v", got)
	}
	if got := ScopesForUserRole("viewer"); len(got) != 1 || got[0] != "role:viewer" {
		t.Fatalf("viewer -> %v", got)
	}
	if got := ScopesForUserRole("member"); len(got) != 1 || got[0] != "role:operator" {
		t.Fatalf("member -> %v", got)
	}
}

func TestSessionTokenPrefix(t *testing.T) {
	tok, err := GenerateSessionToken()
	if err != nil {
		t.Fatal(err)
	}
	if len(tok) < 20 || tok[:9] != "aop_sess_" {
		t.Fatalf("bad token %s", tok)
	}
}
