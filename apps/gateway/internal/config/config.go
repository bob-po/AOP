package config

import (
	"os"
	"strings"
	"time"
)

type Config struct {
	Addr             string
	DatabaseURL      string
	RedisAddr        string
	RedisPassword    string
	DefaultTenantID  string
	OrchestratorURL  string
	OrchestratorURLs []string // For load balancing
	HTTPTimeout      time.Duration
	AuthRequired     bool
	SeedDevKey       bool
}

func Load() Config {
	orchURL := getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8090")
	orchURLsStr := getenv("ORCHESTRATOR_URLS", "")

	var orchURLs []string
	if orchURLsStr != "" {
		orchURLs = strings.Split(orchURLsStr, ",")
		for i, url := range orchURLs {
			orchURLs[i] = strings.TrimSpace(url)
		}
	} else {
		orchURLs = []string{orchURL}
	}

	// Local `go run` stays open by default; deploy compose sets AUTH_REQUIRED=true.
	authRequired := getenvBool("AUTH_REQUIRED", false)
	// When auth is on, only seed the hardcoded local key if SEED_DEV_KEY is explicitly enabled.
	seedDefault := !authRequired
	seedDevKey := seedDefault
	if _, set := os.LookupEnv("SEED_DEV_KEY"); set {
		seedDevKey = getenvBool("SEED_DEV_KEY", seedDefault)
	}

	return Config{
		Addr:             getenv("GATEWAY_ADDR", ":8080"),
		DatabaseURL:      getenv("DATABASE_URL", "postgres://aop:aop@127.0.0.1:5432/aop?sslmode=disable"),
		RedisAddr:        getenv("REDIS_ADDR", "127.0.0.1:6379"),
		RedisPassword:    getenv("REDIS_PASSWORD", ""),
		DefaultTenantID:  getenv("DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001"),
		OrchestratorURL:  orchURL,
		OrchestratorURLs: orchURLs,
		HTTPTimeout:      15 * time.Second,
		AuthRequired:     authRequired,
		SeedDevKey:       seedDevKey,
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getenvBool(key string, fallback bool) bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv(key)))
	if v == "" {
		return fallback
	}
	return v == "1" || v == "true" || v == "yes" || v == "on"
}
