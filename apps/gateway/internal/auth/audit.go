package auth

import (
	"context"
	"encoding/json"
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
