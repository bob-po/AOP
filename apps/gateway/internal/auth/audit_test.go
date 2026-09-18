package auth

import "testing"

func TestNullIfEmpty(t *testing.T) {
	if nullIfEmpty("") != nil {
		t.Fatal("empty should be nil")
	}
	if nullIfEmpty("x") != "x" {
		t.Fatal("non-empty should pass through")
	}
}
