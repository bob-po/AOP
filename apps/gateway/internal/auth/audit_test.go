package auth

import (
	"encoding/json"
	"testing"
)

func TestSummarizeAuditLoginAndInvite(t *testing.T) {
	login := AuditEntry{
		Action:  "auth.login",
		Payload: json.RawMessage(`{"email":"sam@aop.local"}`),
	}
	if got := SummarizeAudit(login); got != "sam@aop.local signed in" {
		t.Fatalf("login: %q", got)
	}
	invite := AuditEntry{
		Action:  "auth.invite",
		Payload: json.RawMessage(`{"invited_email":"sam@aop.local","role":"operator"}`),
	}
	if got := SummarizeAudit(invite); got != "Invited sam@aop.local as operator" {
		t.Fatalf("invite: %q", got)
	}
	key := AuditEntry{
		Action:  "api_key.create",
		Payload: json.RawMessage(`{"name":"ci"}`),
	}
	if got := SummarizeAudit(key); got != "Created API key “ci”" {
		t.Fatalf("key: %q", got)
	}
}

func TestGenerateTempPassword(t *testing.T) {
	pw, err := GenerateTempPassword()
	if err != nil {
		t.Fatal(err)
	}
	if len(pw) < 8 || pw[:4] != "Aop-" {
		t.Fatalf("unexpected password %q", pw)
	}
}
