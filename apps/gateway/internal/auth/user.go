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
	"golang.org/x/crypto/bcrypt"
)

const DevAdminEmail = "admin@aop.local"
const DevAdminPassword = "aop_admin_dev"

type User struct {
	ID          string
	TenantID    string
	Email       string
	DisplayName string
	Role        string
	Status      string
}

func HashPassword(password string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func CheckPassword(hash, password string) bool {
	if hash == "" || password == "" {
		return false
	}
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

func HashSessionToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

func GenerateSessionToken() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return "aop_sess_" + hex.EncodeToString(buf), nil
}

// ScopesForUserRole maps users.role → RBAC role tokens.
func ScopesForUserRole(role string) []string {
	switch NormalizeRole(role) {
	case "owner", "admin":
		return []string{"role:admin"}
	case "viewer":
		return []string{"role:viewer"}
	default:
		return []string{"role:operator"}
	}
}

func (s *Store) EnsureDevUser(ctx context.Context, tenantID, password string) error {
	if password == "" {
		password = DevAdminPassword
	}
	var id string
	err := s.DB.QueryRow(ctx, `
		SELECT id::text FROM users
		WHERE tenant_id = $1::uuid AND email = $2
		LIMIT 1
	`, tenantID, DevAdminEmail).Scan(&id)
	if err == nil {
		var hash *string
		_ = s.DB.QueryRow(ctx, `SELECT password_hash FROM users WHERE id = $1::uuid`, id).Scan(&hash)
		if hash == nil || *hash == "" {
			ph, err := HashPassword(password)
			if err != nil {
				return err
			}
			_, err = s.DB.Exec(ctx, `
				UPDATE users SET password_hash = $2, role = 'admin', status = 'active', updated_at = now()
				WHERE id = $1::uuid
			`, id, ph)
			return err
		}
		return nil
	}
	if err != pgx.ErrNoRows {
		return err
	}
	hash, err := HashPassword(password)
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(ctx, `
		INSERT INTO users (tenant_id, email, display_name, role, status, password_hash, created_at, updated_at)
		VALUES ($1::uuid, $2, $3, 'admin', 'active', $4, now(), now())
	`, tenantID, DevAdminEmail, "AOP Admin", hash)
	return err
}

func (s *Store) FindUserByEmail(ctx context.Context, tenantID, email string) (User, string, error) {
	var u User
	var hash *string
	err := s.DB.QueryRow(ctx, `
		SELECT id::text, tenant_id::text, email, COALESCE(display_name, ''), role, status, password_hash
		FROM users
		WHERE tenant_id = $1::uuid AND lower(email) = lower($2) AND status = 'active'
		LIMIT 1
	`, tenantID, strings.TrimSpace(email)).Scan(
		&u.ID, &u.TenantID, &u.Email, &u.DisplayName, &u.Role, &u.Status, &hash,
	)
	if err == pgx.ErrNoRows {
		return User{}, "", fmt.Errorf("invalid credentials")
	}
	if err != nil {
		return User{}, "", err
	}
	if hash == nil || *hash == "" {
		return User{}, "", fmt.Errorf("password login not enabled for user")
	}
	return u, *hash, nil
}

func (s *Store) CreateSession(ctx context.Context, user User, ttl time.Duration) (string, time.Time, error) {
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	raw, err := GenerateSessionToken()
	if err != nil {
		return "", time.Time{}, err
	}
	expires := time.Now().UTC().Add(ttl)
	_, err = s.DB.Exec(ctx, `
		INSERT INTO user_sessions (user_id, tenant_id, token_hash, expires_at, created_at, last_seen_at)
		VALUES ($1::uuid, $2::uuid, $3, $4, now(), now())
	`, user.ID, user.TenantID, HashSessionToken(raw), expires)
	if err != nil {
		return "", time.Time{}, err
	}
	return raw, expires, nil
}

func (s *Store) AuthenticateSession(ctx context.Context, rawToken string) (Principal, error) {
	rawToken = strings.TrimSpace(rawToken)
	if !strings.HasPrefix(rawToken, "aop_sess_") {
		return Principal{}, fmt.Errorf("invalid session token")
	}
	hash := HashSessionToken(rawToken)
	var p Principal
	var userRole string
	err := s.DB.QueryRow(ctx, `
		SELECT s.id::text, u.id::text, u.tenant_id::text, u.email, COALESCE(u.display_name, ''), u.role
		FROM user_sessions s
		JOIN users u ON u.id = s.user_id
		WHERE s.token_hash = $1
		  AND s.expires_at > now()
		  AND s.revoked_at IS NULL
		  AND u.status = 'active'
		LIMIT 1
	`, hash).Scan(&p.SessionID, &p.UserID, &p.TenantID, &p.Email, &p.Name, &userRole)
	if err == pgx.ErrNoRows {
		return Principal{}, fmt.Errorf("invalid or expired session")
	}
	if err != nil {
		return Principal{}, err
	}
	p.Kind = "session"
	p.UserRole = userRole
	p.Scopes = ScopesForUserRole(userRole)
	_, _ = s.DB.Exec(ctx, `UPDATE user_sessions SET last_seen_at = now() WHERE id = $1::uuid`, p.SessionID)
	return p, nil
}

func (s *Store) RevokeSession(ctx context.Context, rawToken string) error {
	hash := HashSessionToken(strings.TrimSpace(rawToken))
	_, err := s.DB.Exec(ctx, `
		UPDATE user_sessions SET revoked_at = now()
		WHERE token_hash = $1 AND revoked_at IS NULL
	`, hash)
	return err
}

func (s *Store) GetUserByID(ctx context.Context, userID string) (User, error) {
	var u User
	err := s.DB.QueryRow(ctx, `
		SELECT id::text, tenant_id::text, email, COALESCE(display_name, ''), role, status
		FROM users WHERE id = $1::uuid
	`, userID).Scan(&u.ID, &u.TenantID, &u.Email, &u.DisplayName, &u.Role, &u.Status)
	if err == pgx.ErrNoRows {
		return User{}, fmt.Errorf("user not found")
	}
	return u, err
}

func (s *Store) RevokeUserSessions(ctx context.Context, userID string) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM user_sessions WHERE user_id = $1::uuid`, userID)
	return err
}
