package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestLoadBalancedProxySkipsUnhealthy(t *testing.T) {
	ok := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"status":"ok"}`))
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok-backend"))
	}))
	defer ok.Close()

	bad := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("bad-backend"))
	}))
	defer bad.Close()

	h := newLoadBalancedProxy([]string{bad.URL, ok.URL})
	lb, okCast := h.(*LoadBalancedProxy)
	if !okCast {
		t.Fatal("expected *LoadBalancedProxy")
	}
	// Force a probe cycle
	lb.refreshHealth()
	time.Sleep(20 * time.Millisecond)
	if lb.HealthyCount() != 1 {
		t.Fatalf("healthy=%d want 1", lb.HealthyCount())
	}

	// Multiple requests should hit the healthy backend only
	for i := 0; i < 6; i++ {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodGet, "/v1/tasks", nil)
		lb.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
		}
		if rec.Body.String() != "ok-backend" {
			t.Fatalf("got body %q", rec.Body.String())
		}
	}
}

func TestLoadBalancedProxyFailOpenWhenAllDown(t *testing.T) {
	down := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("still-serving"))
	}))
	defer down.Close()

	h := newLoadBalancedProxy([]string{down.URL})
	lb := h.(*LoadBalancedProxy)
	lb.refreshHealth()
	if lb.HealthyCount() != 0 {
		t.Fatalf("healthy=%d want 0", lb.HealthyCount())
	}
	rec := httptest.NewRecorder()
	lb.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/x", nil))
	if rec.Code != http.StatusOK || rec.Body.String() != "still-serving" {
		t.Fatalf("fail-open failed: %d %s", rec.Code, rec.Body.String())
	}
}
