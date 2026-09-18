package registry

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

const defaultTenantID = "00000000-0000-0000-0000-000000000001"

type Store struct {
	DB    *pgxpool.Pool
	Redis *redis.Client
}

type AgentRecord struct {
	ID          string          `json:"agent_id"`
	AgentKey    string          `json:"agent_key"`
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Status      string          `json:"status"`
	Version     string          `json:"version,omitempty"`
	Endpoint    string          `json:"endpoint,omitempty"`
	Protocol    string          `json:"protocol"`
	Priority    int             `json:"priority"`
	Skills      []string        `json:"skills"`
	Card        json.RawMessage `json:"card,omitempty"`
	CreatedAt   time.Time       `json:"created_at"`
	UpdatedAt   time.Time       `json:"updated_at"`
}

type RegisterResult struct {
	AgentID string   `json:"agent_id"`
	Status  string   `json:"status"`
	Skills  []string `json:"skills"`
}

func (s *Store) Register(ctx context.Context, tenantID, endpoint string, card AgentCard, cardJSON []byte) (RegisterResult, error) {
	if tenantID == "" {
		tenantID = defaultTenantID
	}
	agentKey := DeriveAgentKey(card, endpoint)
	skillIDs := make([]string, 0, len(card.Skills))
	for _, sk := range card.Skills {
		if sk.ID != "" {
			skillIDs = append(skillIDs, sk.ID)
		}
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return RegisterResult{}, err
	}
	defer tx.Rollback(ctx)

	var agentID string
	var oldStatus string
	err = tx.QueryRow(ctx, `
		SELECT id::text, status FROM agents
		WHERE tenant_id = $1::uuid AND agent_key = $2
	`, tenantID, agentKey).Scan(&agentID, &oldStatus)

	status := "online"
	now := time.Now().UTC()

	if err == pgx.ErrNoRows {
		err = tx.QueryRow(ctx, `
			INSERT INTO agents (
				tenant_id, agent_key, name, description, protocol, status,
				current_version, card_json, priority, created_at, updated_at
			) VALUES (
				$1::uuid, $2, $3, $4, 'A2A', $5, $6, $7::jsonb, 100, $8, $8
			) RETURNING id::text
		`, tenantID, agentKey, card.Name, card.Description, status, card.Version, cardJSON, now).Scan(&agentID)
		if err != nil {
			return RegisterResult{}, fmt.Errorf("insert agent: %w", err)
		}
	} else if err != nil {
		return RegisterResult{}, fmt.Errorf("lookup agent: %w", err)
	} else {
		_, err = tx.Exec(ctx, `
			UPDATE agents SET
				name = $2,
				description = $3,
				status = $4,
				current_version = $5,
				card_json = $6::jsonb,
				updated_at = $7
			WHERE id = $1::uuid
		`, agentID, card.Name, card.Description, status, card.Version, cardJSON, now)
		if err != nil {
			return RegisterResult{}, fmt.Errorf("update agent: %w", err)
		}
		_, _ = tx.Exec(ctx, `DELETE FROM agent_skills WHERE agent_id = $1::uuid`, agentID)
		_, _ = tx.Exec(ctx, `DELETE FROM agent_endpoints WHERE agent_id = $1::uuid`, agentID)
	}

	_, err = tx.Exec(ctx, `
		INSERT INTO agent_versions (agent_id, version, card_json, is_active, created_at)
		VALUES ($1::uuid, $2, $3::jsonb, true, $4)
		ON CONFLICT (agent_id, version) DO UPDATE SET
			card_json = EXCLUDED.card_json,
			is_active = true
	`, agentID, card.Version, cardJSON, now)
	if err != nil {
		return RegisterResult{}, fmt.Errorf("upsert version: %w", err)
	}

	endpointURL := card.URL
	if endpointURL == "" {
		endpointURL = endpoint
	}
	_, err = tx.Exec(ctx, `
		INSERT INTO agent_endpoints (agent_id, url, auth_type, is_primary, created_at, updated_at)
		VALUES ($1::uuid, $2, 'none', true, $3, $3)
	`, agentID, endpointURL, now)
	if err != nil {
		return RegisterResult{}, fmt.Errorf("insert endpoint: %w", err)
	}

	for _, sk := range card.Skills {
		if sk.ID == "" {
			continue
		}
		name := sk.Name
		if name == "" {
			name = sk.ID
		}
		_, err = tx.Exec(ctx, `
			INSERT INTO agent_skills (agent_id, skill_id, name, description, created_at)
			VALUES ($1::uuid, $2, $3, $4, $5)
			ON CONFLICT (agent_id, skill_id) DO UPDATE SET
				name = EXCLUDED.name,
				description = EXCLUDED.description
		`, agentID, sk.ID, name, sk.Description, now)
		if err != nil {
			return RegisterResult{}, fmt.Errorf("insert skill %s: %w", sk.ID, err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return RegisterResult{}, err
	}

	if err := s.syncRedis(ctx, agentID, skillIDs, status); err != nil {
		return RegisterResult{}, fmt.Errorf("redis sync: %w", err)
	}

	_ = oldStatus
	return RegisterResult{
		AgentID: agentID,
		Status:  status,
		Skills:  skillIDs,
	}, nil
}

func (s *Store) List(ctx context.Context, tenantID, skill, status string) ([]AgentRecord, error) {
	if tenantID == "" {
		tenantID = defaultTenantID
	}
	query := `
		SELECT a.id::text, a.agent_key, a.name, COALESCE(a.description, ''), a.status,
		       COALESCE(a.current_version, ''), a.protocol, a.priority, a.created_at, a.updated_at,
		       COALESCE((
		         SELECT e.url FROM agent_endpoints e
		         WHERE e.agent_id = a.id AND e.is_primary = true
		         ORDER BY e.updated_at DESC LIMIT 1
		       ), ''),
		       COALESCE((
		         SELECT array_agg(s.skill_id ORDER BY s.skill_id)
		         FROM agent_skills s WHERE s.agent_id = a.id
		       ), '{}')
		FROM agents a
		WHERE a.tenant_id = $1::uuid
	`
	args := []any{tenantID}
	argN := 2
	if skill != "" {
		query += fmt.Sprintf(` AND EXISTS (
			SELECT 1 FROM agent_skills s WHERE s.agent_id = a.id AND s.skill_id = $%d
		)`, argN)
		args = append(args, skill)
		argN++
	}
	if status != "" {
		query += fmt.Sprintf(` AND a.status = $%d`, argN)
		args = append(args, status)
	}
	query += ` ORDER BY a.priority ASC, a.name ASC`

	rows, err := s.DB.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]AgentRecord, 0)
	for rows.Next() {
		var rec AgentRecord
		var skills []string
		if err := rows.Scan(
			&rec.ID, &rec.AgentKey, &rec.Name, &rec.Description, &rec.Status,
			&rec.Version, &rec.Protocol, &rec.Priority, &rec.CreatedAt, &rec.UpdatedAt,
			&rec.Endpoint, &skills,
		); err != nil {
			return nil, err
		}
		rec.Skills = skills
		out = append(out, rec)
	}
	return out, rows.Err()
}

func (s *Store) Get(ctx context.Context, tenantID, agentID string) (AgentRecord, error) {
	if tenantID == "" {
		tenantID = defaultTenantID
	}
	var rec AgentRecord
	var skills []string
	var card []byte
	err := s.DB.QueryRow(ctx, `
		SELECT a.id::text, a.agent_key, a.name, COALESCE(a.description, ''), a.status,
		       COALESCE(a.current_version, ''), a.protocol, a.priority, a.created_at, a.updated_at,
		       COALESCE((
		         SELECT e.url FROM agent_endpoints e
		         WHERE e.agent_id = a.id AND e.is_primary = true
		         ORDER BY e.updated_at DESC LIMIT 1
		       ), ''),
		       COALESCE((
		         SELECT array_agg(s.skill_id ORDER BY s.skill_id)
		         FROM agent_skills s WHERE s.agent_id = a.id
		       ), '{}'),
		       COALESCE(a.card_json, '{}'::jsonb)
		FROM agents a
		WHERE a.tenant_id = $1::uuid AND (a.id::text = $2 OR a.agent_key = $2)
	`, tenantID, agentID).Scan(
		&rec.ID, &rec.AgentKey, &rec.Name, &rec.Description, &rec.Status,
		&rec.Version, &rec.Protocol, &rec.Priority, &rec.CreatedAt, &rec.UpdatedAt,
		&rec.Endpoint, &skills, &card,
	)
	if err == pgx.ErrNoRows {
		return AgentRecord{}, ErrNotFound
	}
	if err != nil {
		return AgentRecord{}, err
	}
	rec.Skills = skills
	rec.Card = card
	return rec, nil
}

func (s *Store) SetStatus(ctx context.Context, tenantID, agentID, status string) (AgentRecord, error) {
	rec, err := s.Get(ctx, tenantID, agentID)
	if err != nil {
		return AgentRecord{}, err
	}
	_, err = s.DB.Exec(ctx, `
		UPDATE agents SET status = $2, updated_at = now() WHERE id = $1::uuid
	`, rec.ID, status)
	if err != nil {
		return AgentRecord{}, err
	}
	if err := s.syncRedis(ctx, rec.ID, rec.Skills, status); err != nil {
		return AgentRecord{}, err
	}
	rec.Status = status
	return rec, nil
}

func (s *Store) Delete(ctx context.Context, tenantID, agentID string) error {
	rec, err := s.Get(ctx, tenantID, agentID)
	if err != nil {
		return err
	}
	_, err = s.DB.Exec(ctx, `DELETE FROM agents WHERE id = $1::uuid`, rec.ID)
	if err != nil {
		return err
	}
	return s.syncRedis(ctx, rec.ID, rec.Skills, "disabled")
}

func (s *Store) syncRedis(ctx context.Context, agentID string, skills []string, status string) error {
	if s.Redis == nil {
		return nil
	}
	pipe := s.Redis.Pipeline()

	// Clear membership for known skills then re-add if online.
	// Also keep a reverse set of skills for this agent.
	oldSkills, _ := s.Redis.SMembers(ctx, "agent:"+agentID+":skills").Result()
	for _, sk := range oldSkills {
		pipe.SRem(ctx, "agent:skill:"+sk, agentID)
	}
	pipe.Del(ctx, "agent:"+agentID+":skills")

	pipe.HSet(ctx, "agent:"+agentID+":state", map[string]any{
		"status":     status,
		"updated_at": time.Now().UTC().Format(time.RFC3339),
	})

	if status == "online" || status == "running" {
		for _, sk := range skills {
			pipe.SAdd(ctx, "agent:skill:"+sk, agentID)
			pipe.SAdd(ctx, "agent:"+agentID+":skills", sk)
		}
	}

	_, err := pipe.Exec(ctx)
	return err
}

var ErrNotFound = fmt.Errorf("agent not found")
