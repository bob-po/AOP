package httpapi

import (
	"context"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	lbHealthyTargets = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "aop_gateway_lb_healthy_targets",
		Help: "Number of healthy orchestrator targets",
	})
	lbTotalTargets = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "aop_gateway_lb_targets",
		Help: "Total configured orchestrator targets",
	})
	lbProxyRequests = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "aop_gateway_proxy_requests_total",
		Help: "Orchestrator proxy requests by result",
	}, []string{"result"})
)

// LoadBalancedProxy round-robins across healthy orchestrator instances.
type LoadBalancedProxy struct {
	targets []*url.URL
	proxies map[string]*httputil.ReverseProxy
	healthy []bool
	rr      uint64
	mu      sync.RWMutex
	client  *http.Client
	stop    chan struct{}
}

func newLoadBalancedProxy(targets []string) http.Handler {
	parsedTargets := make([]*url.URL, 0, len(targets))
	proxies := make(map[string]*httputil.ReverseProxy)
	healthy := make([]bool, 0, len(targets))

	for _, target := range targets {
		u, err := url.Parse(strings.TrimRight(target, "/"))
		if err != nil {
			panic(err)
		}
		parsedTargets = append(parsedTargets, u)
		healthy = append(healthy, true) // optimistic until first probe

		proxy := httputil.NewSingleHostReverseProxy(u)
		original := proxy.Director
		targetURL := u
		proxy.Director = func(req *http.Request) {
			ctx := req.Context()
			original(req)
			req.Host = targetURL.Host
			req.Header.Set("X-Forwarded-Host", req.Header.Get("Host"))
			if p, ok := PrincipalFromContext(ctx); ok {
				req.Header.Set("X-Tenant-ID", p.TenantID)
				req.Header.Set("X-API-Key-ID", p.APIKeyID)
			}
		}
		proxies[u.String()] = proxy
	}

	lb := &LoadBalancedProxy{
		targets: parsedTargets,
		proxies: proxies,
		healthy: healthy,
		client: &http.Client{
			Timeout: 2 * time.Second,
		},
		stop: make(chan struct{}),
	}
	lbTotalTargets.Set(float64(len(parsedTargets)))
	lbHealthyTargets.Set(float64(len(parsedTargets)))
	lb.refreshHealth()
	go lb.healthLoop(5 * time.Second)
	return lb
}

func (lb *LoadBalancedProxy) healthLoop(interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-lb.stop:
			return
		case <-t.C:
			lb.refreshHealth()
		}
	}
}

func (lb *LoadBalancedProxy) refreshHealth() {
	type result struct {
		i       int
		healthy bool
	}
	ch := make(chan result, len(lb.targets))
	for i, u := range lb.targets {
		i, u := i, u
		go func() {
			ch <- result{i: i, healthy: lb.probe(u)}
		}()
	}
	next := make([]bool, len(lb.targets))
	for range lb.targets {
		r := <-ch
		next[r.i] = r.healthy
	}
	healthyCount := 0
	for _, ok := range next {
		if ok {
			healthyCount++
		}
	}
	lb.mu.Lock()
	lb.healthy = next
	lb.mu.Unlock()
	lbHealthyTargets.Set(float64(healthyCount))
}

func (lb *LoadBalancedProxy) probe(u *url.URL) bool {
	healthURL := *u
	healthURL.Path = "/health"
	healthURL.RawQuery = ""
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, healthURL.String(), nil)
	if err != nil {
		return false
	}
	resp, err := lb.client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	return resp.StatusCode == http.StatusOK
}

func (lb *LoadBalancedProxy) pick() (*url.URL, *httputil.ReverseProxy, bool) {
	lb.mu.RLock()
	defer lb.mu.RUnlock()
	n := len(lb.targets)
	if n == 0 {
		return nil, nil, false
	}
	start := int(atomic.AddUint64(&lb.rr, 1)-1) % n
	// Prefer healthy
	for i := 0; i < n; i++ {
		idx := (start + i) % n
		if lb.healthy[idx] {
			u := lb.targets[idx]
			return u, lb.proxies[u.String()], true
		}
	}
	// Fail open to round-robin if all marked unhealthy (avoid total outage on probe flakes)
	u := lb.targets[start]
	return u, lb.proxies[u.String()], false
}

func (lb *LoadBalancedProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	target, proxy, healthy := lb.pick()
	if target == nil || proxy == nil {
		lbProxyRequests.WithLabelValues("no_targets").Inc()
		http.Error(w, "No available orchestrator instances", http.StatusServiceUnavailable)
		return
	}
	if healthy {
		lbProxyRequests.WithLabelValues("ok").Inc()
	} else {
		lbProxyRequests.WithLabelValues("degraded").Inc()
		log.Printf("lb: all orchestrators unhealthy; fail-open to %s", target.Host)
	}
	proxy.ServeHTTP(w, r)
}

// HealthyCount returns how many targets currently pass health checks (for tests).
func (lb *LoadBalancedProxy) HealthyCount() int {
	lb.mu.RLock()
	defer lb.mu.RUnlock()
	n := 0
	for _, ok := range lb.healthy {
		if ok {
			n++
		}
	}
	return n
}

// NewLoadBalancedProxy creates a health-aware load-balanced proxy.
func NewLoadBalancedProxy(targets []string) http.Handler {
	return newLoadBalancedProxy(targets)
}

// NewOrchestratorProxy creates a single-host reverse proxy.
func NewOrchestratorProxy(target string) http.Handler {
	return newOrchestratorProxy(target)
}

func newOrchestratorProxy(target string) http.Handler {
	u, err := url.Parse(strings.TrimRight(target, "/"))
	if err != nil {
		panic(err)
	}
	proxy := httputil.NewSingleHostReverseProxy(u)
	original := proxy.Director
	proxy.Director = func(req *http.Request) {
		ctx := req.Context()
		original(req)
		req.Host = u.Host
		req.Header.Set("X-Forwarded-Host", req.Header.Get("Host"))
		if p, ok := PrincipalFromContext(ctx); ok {
			req.Header.Set("X-Tenant-ID", p.TenantID)
			req.Header.Set("X-API-Key-ID", p.APIKeyID)
		}
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lbProxyRequests.WithLabelValues("single").Inc()
		proxy.ServeHTTP(w, r)
	})
}
