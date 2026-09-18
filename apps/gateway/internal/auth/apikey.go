package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const DevAPIKey = "aop_sk_dev_local_0000000000000001"

type Principal struct {
	APIKeyID  string
	SessionID string
	UserID    string
	TenantID  string
	Name      string
	Email     string
	UserRole  string
	Kind      string // api_key | session
	Scopes    []string
}

type Store struct {
	DB *pgxpool.Pool
}

func HashKey(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

func Prefix(raw string) string {
	if len(raw) <= 12 {
		return raw
	}
	return raw[:12]
}

func GenerateKey() (string, error) {
	buf := make([]byte, 24)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return "aop_sk_" + hex.EncodeToString(buf), nil
}

func (s *Store) EnsureDevKey(ctx context.Context, tenantID string) error {
	hash := HashKey(DevAPIKey)
	var id string
	err := s.DB.QueryRow(ctx, `
		SELECT id::text FROM api_keys
		WHERE tenant_id = $1::uuid AND key_hash = $2 AND status = 'active'
		LIMIT 1
	`, tenantID, hash).Scan(&id)
	if err == nil {
		return nil
	}
	if err != pgx.ErrNoRows {
		return err
	}
	_, err = s.DB.Exec(ctx, `
		INSERT INTO api_keys (tenant_id, name, key_prefix, key_hash, scopes, status, created_at)
		VALUES ($1::uuid, $2, $3, $4, $5, 'active', $6)
	`, tenantID, "local-dev", Prefix(DevAPIKey), hash, []string{"*"}, time.Now().UTC())
	return err
}

func (s *Store) Authenticate(ctx context.Context, rawKey string) (Principal, error) {
	rawKey = strings.TrimSpace(rawKey)
	if rawKey == "" {
		return Principal{}, fmt.Errorf("missing api key")
	}
	if strings.HasPrefix(rawKey, "aop_sess_") {
		return s.AuthenticateSession(ctx, rawKey)
	}
	return s.AuthenticateAPIKey(ctx, rawKey)
}

func (s *Store) AuthenticateAPIKey(ctx context.Context, rawKey string) (Principal, error) {
	rawKey = strings.TrimSpace(rawKey)
	if rawKey == "" {
		return Principal{}, fmt.Errorf("missing api key")
	}
	hash := HashKey(rawKey)
	var p Principal
	var scopes []string
	err := s.DB.QueryRow(ctx, `
		SELECT id::text, tenant_id::text, name, scopes
		FROM api_keys
		WHERE key_hash = $1 AND status = 'active'
		  AND (expires_at IS NULL OR expires_at > now())
		LIMIT 1
	`, hash).Scan(&p.APIKeyID, &p.TenantID, &p.Name, &scopes)
	if err == pgx.ErrNoRows {
		return Principal{}, fmt.Errorf("invalid api key")
	}
	if err != nil {
		return Principal{}, err
	}
	p.Kind = "api_key"
	p.Scopes = scopes
	_, _ = s.DB.Exec(ctx, `UPDATE api_keys SET last_used_at = now() WHERE id = $1::uuid`, p.APIKeyID)
	return p, nil
}

func (s *Store) HasScope(p Principal, need string) bool {
	need = strings.TrimSpace(need)
	if need == "" {
		return true
	}
	expanded := ExpandScopes(p.Scopes)
	for _, sc := range expanded {
		sc = strings.TrimSpace(sc)
		if sc == "*" || sc == "admin" || sc == need {
			return true
		}
		// api_key.admin covers admin-style key management aliases
		if need == "api_key.admin" && (sc == "admin" || sc == "api_key.admin") {
			return true
		}
		// agent.write covers legacy agent.register
		if need == "agent.write" && sc == "agent.register" {
			return true
		}
		if need == "agent.register" && sc == "agent.write" {
			return true
		}
	}
	return false
}

type APIKeyRecord struct {
	ID        string     `json:"id"`
	Name      string     `json:"name"`
	Prefix    string     `json:"key_prefix"`
	Scopes    []string   `json:"scopes"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
	ExpiresAt *time.Time `json:"expires_at,omitempty"`
	LastUsed  *time.Time `json:"last_used_at,omitempty"`
	// only on create
	APIKey string `json:"api_key,omitempty"`
}

func (s *Store) List(ctx context.Context, tenantID string) ([]APIKeyRecord, error) {
	rows, err := s.DB.Query(ctx, `
		SELECT id::text, name, key_prefix, scopes, status, created_at, expires_at, last_used_at
		FROM api_keys
		WHERE tenant_id = $1::uuid
		ORDER BY created_at DESC
	`, tenantID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]APIKeyRecord, 0)
	for rows.Next() {
		var r APIKeyRecord
		if err := rows.Scan(&r.ID, &r.Name, &r.Prefix, &r.Scopes, &r.Status, &r.CreatedAt, &r.ExpiresAt, &r.LastUsed); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s *Store) Create(ctx context.Context, tenantID, name string, scopes []string) (APIKeyRecord, error) {
	if name == "" {
		name = "api-key"
	}
	if len(scopes) == 0 {
		scopes = []string{"role:operator"}
	}
	// Normalize bare role names to role:<name> for clarity in storage
	normalized := make([]string, 0, len(scopes))
	for _, sc := range scopes {
		sc = strings.TrimSpace(sc)
		if sc == "" {
			continue
		}
		role := NormalizeRole(sc)
		if _, ok := RoleCatalog[role]; ok {
			normalized = append(normalized, "role:"+role)
			continue
		}
		normalized = append(normalized, sc)
	}
	if len(normalized) == 0 {
		normalized = []string{"role:operator"}
	}
	scopes = normalized
	raw, err := GenerateKey()
	if err != nil {
		return APIKeyRecord{}, err
	}
	now := time.Now().UTC()
	var id string
	err = s.DB.QueryRow(ctx, `
		INSERT INTO api_keys (tenant_id, name, key_prefix, key_hash, scopes, status, created_at)
		VALUES ($1::uuid, $2, $3, $4, $5, 'active', $6)
		RETURNING id::text
	`, tenantID, name, Prefix(raw), HashKey(raw), scopes, now).Scan(&id)
	if err != nil {
		return APIKeyRecord{}, err
	}
	return APIKeyRecord{
		ID:        id,
		Name:      name,
		Prefix:    Prefix(raw),
		Scopes:    scopes,
		Status:    "active",
		CreatedAt: now,
		APIKey:    raw,
	}, nil
}

func (s *Store) Revoke(ctx context.Context, tenantID, keyID string) error {
	tag, err := s.DB.Exec(ctx, `
		UPDATE api_keys SET status = 'revoked'
		WHERE tenant_id = $1::uuid AND id::text = $2
	`, tenantID, keyID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("api key not found")
	}
	return nil
}
