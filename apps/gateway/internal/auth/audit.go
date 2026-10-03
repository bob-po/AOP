package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type AuditEntry struct {
	ID           int64           `json:"id"`
	TenantID     *string         `json:"tenant_id,omitempty"`
	Action       string          `json:"action"`
	ResourceType string          `json:"resource_type,omitempty"`
	ResourceID   string          `json:"resource_id,omitempty"`
	IP           string          `json:"ip,omitempty"`
	Payload      json.RawMessage `json:"payload,omitempty"`
	CreatedAt    time.Time       `json:"created_at"`
	Summary      string          `json:"summary"`
}

type AuditStore struct {
	DB *pgxpool.Pool
}

func (s *AuditStore) Append(
	ctx context.Context,
	tenantID, action, resourceType, resourceID, ip string,
	payload map[string]any,
) error {
	if s == nil || s.DB == nil || action == "" {
		return nil
	}
	var raw []byte
	if payload != nil {
		raw, _ = json.Marshal(payload)
	} else {
		raw = []byte("{}")
	}
	var tid any
	if tenantID != "" {
		tid = tenantID
	}
	_, err := s.DB.Exec(ctx, `
		INSERT INTO audit_logs (tenant_id, action, resource_type, resource_id, ip, payload, created_at)
		VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7)
	`, tid, action, nullIfEmpty(resourceType), nullIfEmpty(resourceID), nullIfEmpty(ip), string(raw), time.Now().UTC())
	return err
}

func (s *AuditStore) List(ctx context.Context, tenantID string, limit int) ([]AuditEntry, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := s.DB.Query(ctx, `
		SELECT id, tenant_id::text, action,
		       COALESCE(resource_type, ''), COALESCE(resource_id, ''),
		       COALESCE(ip, ''), COALESCE(payload, '{}'::jsonb), created_at
		FROM audit_logs
		WHERE ($1 = '' OR tenant_id = $1::uuid)
		ORDER BY created_at DESC
		LIMIT $2
	`, tenantID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]AuditEntry, 0)
	for rows.Next() {
		var e AuditEntry
		var tid *string
		var payload []byte
		if err := rows.Scan(&e.ID, &tid, &e.Action, &e.ResourceType, &e.ResourceID, &e.IP, &payload, &e.CreatedAt); err != nil {
			return nil, err
		}
		e.TenantID = tid
		e.Payload = payload
		e.Summary = SummarizeAudit(e)
		out = append(out, e)
	}
	return out, rows.Err()
}

func nullIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func payloadString(p map[string]any, key string) string {
	if p == nil {
		return ""
	}
	v, ok := p[key]
	if !ok || v == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(v))
}

// SummarizeAudit turns a raw audit row into one operator-readable sentence.
func SummarizeAudit(e AuditEntry) string {
	var p map[string]any
	if len(e.Payload) > 0 {
		_ = json.Unmarshal(e.Payload, &p)
	}
	who := payloadString(p, "email")
	if who == "" {
		who = payloadString(p, "api_key_name")
	}
	if who == "" {
		who = payloadString(p, "name")
	}
	switch e.Action {
	case "auth.login":
		if who != "" {
			return who + " signed in"
		}
		return "Someone signed in"
	case "auth.logout":
		if who != "" {
			return who + " signed out"
		}
		return "Session ended"
	case "auth.invite":
		email := payloadString(p, "invited_email")
		if email == "" {
			email = payloadString(p, "email")
		}
		role := payloadString(p, "role")
		if email != "" && role != "" {
			return "Invited " + email + " as " + role
		}
		if email != "" {
			return "Invited " + email
		}
		return "Invited a teammate"
	case "api_key.create":
		name := payloadString(p, "name")
		if name != "" {
			return "Created API key “" + name + "”"
		}
		return "Created an API key"
	case "api_key.revoke":
		if e.ResourceID != "" {
			return "Revoked API key " + e.ResourceID
		}
		return "Revoked an API key"
	default:
		if who != "" {
			return who + " · " + e.Action
		}
		if e.ResourceType != "" && e.ResourceID != "" {
			return e.Action + " on " + e.ResourceType + " " + e.ResourceID
		}
		return e.Action
	}
}
