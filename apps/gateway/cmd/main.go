package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"

	"github.com/aop/a2a-platform/apps/gateway/internal/auth"
	"github.com/aop/a2a-platform/apps/gateway/internal/config"
	"github.com/aop/a2a-platform/apps/gateway/internal/httpapi"
	"github.com/aop/a2a-platform/apps/gateway/internal/registry"
)

func main() {
	cfg := config.Load()
	ctx := context.Background()

	pool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("postgres connect: %v", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		log.Fatalf("postgres ping: %v", err)
	}

	rdb := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisAddr,
		Password: cfg.RedisPassword,
	})
	defer rdb.Close()
	if err := rdb.Ping(ctx).Err(); err != nil {
		log.Fatalf("redis ping: %v", err)
	}

	authStore := &auth.Store{DB: pool}
	auditStore := &auth.AuditStore{DB: pool}
	if cfg.SeedDevKey {
		if err := authStore.EnsureDevKey(ctx, cfg.DefaultTenantID); err != nil {
			log.Fatalf("seed api key: %v", err)
		}
		log.Printf(
			"dev api key seeded (AUTH_REQUIRED=%v): prefix=%s… (plaintext not logged; set SEED_DEV_KEY=false to skip)",
			cfg.AuthRequired,
			auth.Prefix(auth.DevAPIKey),
		)
	} else {
		log.Printf("SEED_DEV_KEY=false — skipping local-dev key seed (AUTH_REQUIRED=%v)", cfg.AuthRequired)
	}
	adminPass := os.Getenv("SEED_ADMIN_PASSWORD")
	if adminPass == "" {
		adminPass = auth.DevAdminPassword
	}
	if err := authStore.EnsureDevUser(ctx, cfg.DefaultTenantID, adminPass); err != nil {
		log.Fatalf("seed admin user: %v", err)
	}
	log.Printf("admin user ready: %s (override password via SEED_ADMIN_PASSWORD)", auth.DevAdminEmail)

	store := &registry.Store{DB: pool, Redis: rdb}
	fetcher := registry.NewCardFetcher(cfg.HTTPTimeout)

	// Choose proxy based on whether we have multiple orchestrator URLs
	var orchestratorProxy http.Handler
	if len(cfg.OrchestratorURLs) > 1 {
		orchestratorProxy = httpapi.NewLoadBalancedProxy(cfg.OrchestratorURLs)
	} else {
		orchestratorProxy = httpapi.NewOrchestratorProxy(cfg.OrchestratorURLs[0])
	}

	server := &httpapi.Server{
		Agents: &httpapi.AgentHandlers{
			Store:   store,
			Fetcher: fetcher,
			Tenant:  cfg.DefaultTenantID,
			Auth:    authStore,
			Audit:   auditStore,
		},
		APIKeys: &httpapi.APIKeyHandlers{
			Store:  authStore,
			Audit:  auditStore,
			Tenant: cfg.DefaultTenantID,
			AuthOn: cfg.AuthRequired,
		},
		RBAC: &httpapi.RBACHandlers{
			Store:  authStore,
			AuthOn: cfg.AuthRequired,
		},
		Audit: &httpapi.AuditHandlers{
			Store:  auditStore,
			Auth:   authStore,
			Tenant: cfg.DefaultTenantID,
			AuthOn: cfg.AuthRequired,
		},
		AuthAPI: &httpapi.AuthHandlers{
			Store:  authStore,
			Audit:  auditStore,
			Tenant: cfg.DefaultTenantID,
			AuthOn: cfg.AuthRequired,
		},
		AuthStore:         authStore,
		AuthRequired:      cfg.AuthRequired,
		DefaultTenantID:   cfg.DefaultTenantID,
		OrchestratorProxy: orchestratorProxy,
	}

	httpServer := &http.Server{
		Addr:              cfg.Addr,
		Handler:           server.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("AOP Gateway listening on %s", cfg.Addr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(shutdownCtx)
	fmt.Println("gateway stopped")
}
