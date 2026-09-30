package registry

import (
	"fmt"
	"net"
	"net/url"
	"os"
	"strings"
)

const maxCardBodyBytes = 256 * 1024

// ValidateAgentEndpoint rejects dangerous schemes/hosts before outbound fetch.
// Local/private endpoints are allowed by default (edge agents on loopback);
// set AGENT_ENDPOINT_ALLOW_PRIVATE=0 to refuse RFC1918 / link-local / loopback.
func ValidateAgentEndpoint(endpoint string) error {
	base, err := normalizeBase(endpoint)
	if err != nil {
		return err
	}
	u, err := url.Parse(base)
	if err != nil {
		return fmt.Errorf("invalid endpoint: %w", err)
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" {
		return fmt.Errorf("endpoint scheme must be http or https")
	}
	host := u.Hostname()
	if host == "" {
		return fmt.Errorf("invalid endpoint host")
	}
	// Always block cloud metadata / link-local.
	if isBlockedMetadataHost(host) {
		return fmt.Errorf("endpoint host is not allowed")
	}
	allowPrivate := envTruthyDefault("AGENT_ENDPOINT_ALLOW_PRIVATE", true)
	if !allowPrivate && isPrivateOrLoopbackHost(host) {
		return fmt.Errorf("private/loopback agent endpoints are disabled")
	}
	return nil
}

func isBlockedMetadataHost(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	if h == "metadata.google.internal" || h == "metadata" {
		return true
	}
	ip := net.ParseIP(h)
	if ip == nil {
		return false
	}
	// 169.254.0.0/16 link-local (includes AWS/GCP metadata 169.254.169.254)
	if ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() {
		return true
	}
	return false
}

func isPrivateOrLoopbackHost(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	if h == "localhost" {
		return true
	}
	ip := net.ParseIP(h)
	if ip == nil {
		return false
	}
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast()
}

func envTruthyDefault(key string, defaultVal bool) bool {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return defaultVal
	}
	switch strings.ToLower(raw) {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return defaultVal
	}
}
