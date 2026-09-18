package auth

import "testing"

func TestHasScope(t *testing.T) {
	s := &Store{}
	cases := []struct {
		scopes []string
		need   string
		want   bool
	}{
		{[]string{"*"}, "task.write", true},
		{[]string{"admin"}, "agent.write", true},
		{[]string{"task.write"}, "task.write", true},
		{[]string{"task.read"}, "task.write", false},
		{[]string{"agent.write"}, "task.write", false},
		{[]string{"api_key.admin"}, "api_key.admin", true},
		{[]string{"admin"}, "api_key.admin", true},
		{[]string{"role:viewer"}, "task.read", true},
		{[]string{"role:viewer"}, "task.write", false},
		{[]string{"role:operator"}, "agent.write", true},
		{[]string{}, "task.write", false},
	}
	for _, tc := range cases {
		p := Principal{Scopes: tc.scopes}
		if got := s.HasScope(p, tc.need); got != tc.want {
			t.Fatalf("scopes=%v need=%s got=%v want=%v", tc.scopes, tc.need, got, tc.want)
		}
	}
}
