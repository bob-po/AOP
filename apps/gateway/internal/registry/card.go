package registry

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode"
)

type AgentCard struct {
	Name               string         `json:"name"`
	Description        string         `json:"description"`
	URL                string         `json:"url"`
	Version            string         `json:"version"`
	ProtocolVersion    string         `json:"protocolVersion"`
	Capabilities       map[string]any `json:"capabilities"`
	DefaultInputModes  []string       `json:"defaultInputModes"`
	DefaultOutputModes []string       `json:"defaultOutputModes"`
	Skills             []Skill        `json:"skills"`
}

type Skill struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags"`
	Examples    []string `json:"examples"`
	InputModes  []string `json:"inputModes"`
	OutputModes []string `json:"outputModes"`
}

type CardFetcher struct {
	Client *http.Client
}

func NewCardFetcher(timeout time.Duration) *CardFetcher {
	return &CardFetcher{
		Client: &http.Client{Timeout: timeout},
	}
}

func (f *CardFetcher) Fetch(ctx context.Context, endpoint string) (AgentCard, []byte, error) {
	base, err := normalizeBase(endpoint)
	if err != nil {
		return AgentCard{}, nil, err
	}

	paths := []string{
		"/.well-known/agent-card.json",
		"/.well-known/agent.json",
	}

	var lastErr error
	for _, p := range paths {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+p, nil)
		if err != nil {
			lastErr = err
			continue
		}
		resp, err := f.Client.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		body, readErr := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			continue
		}
		if resp.StatusCode == http.StatusNotFound {
			lastErr = fmt.Errorf("%s: 404", p)
			continue
		}
		if resp.StatusCode >= 300 {
			lastErr = fmt.Errorf("%s: status %d", p, resp.StatusCode)
			continue
		}
		var card AgentCard
		if err := json.Unmarshal(body, &card); err != nil {
			lastErr = fmt.Errorf("%s: invalid json: %w", p, err)
			continue
		}
		if card.URL == "" {
			card.URL = base + "/"
		}
		if card.Version == "" {
			card.Version = "0.0.0"
		}
		return card, body, nil
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("agent card not found")
	}
	return AgentCard{}, nil, lastErr
}

func (f *CardFetcher) Health(ctx context.Context, endpoint string) error {
	base, err := normalizeBase(endpoint)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/health", nil)
	if err != nil {
		return err
	}
	resp, err := f.Client.Do(req)
	if err != nil {
		// fallback: card endpoint proves reachability
		_, _, cardErr := f.Fetch(ctx, endpoint)
		return cardErr
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		_, _, cardErr := f.Fetch(ctx, endpoint)
		return cardErr
	}
	return nil
}

func normalizeBase(endpoint string) (string, error) {
	endpoint = strings.TrimSpace(endpoint)
	if endpoint == "" {
		return "", fmt.Errorf("endpoint is required")
	}
	if !strings.Contains(endpoint, "://") {
		endpoint = "http://" + endpoint
	}
	u, err := url.Parse(endpoint)
	if err != nil {
		return "", fmt.Errorf("invalid endpoint: %w", err)
	}
	if u.Scheme == "" || u.Host == "" {
		return "", fmt.Errorf("invalid endpoint url")
	}
	u.Path = strings.TrimRight(u.Path, "/")
	u.RawQuery = ""
	u.Fragment = ""
	return strings.TrimRight(u.String(), "/"), nil
}

func DeriveAgentKey(card AgentCard, endpoint string) string {
	if card.Name != "" {
		return slugify(card.Name)
	}
	base, err := normalizeBase(endpoint)
	if err != nil {
		return "agent"
	}
	u, _ := url.Parse(base)
	if u != nil && u.Hostname() != "" {
		return slugify(u.Hostname())
	}
	return "agent"
}

func slugify(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	var b strings.Builder
	prevDash := false
	for _, r := range s {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
			prevDash = false
			continue
		}
		if !prevDash {
			b.WriteByte('-')
			prevDash = true
		}
	}
	out := strings.Trim(b.String(), "-")
	if out == "" {
		return "agent"
	}
	return out
}
