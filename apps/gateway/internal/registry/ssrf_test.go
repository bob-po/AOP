package registry

import "testing"

func TestValidateAgentEndpointBlocksMetadata(t *testing.T) {
	err := ValidateAgentEndpoint("http://169.254.169.254/latest/meta-data/")
	if err == nil {
		t.Fatal("expected metadata host to be blocked")
	}
}

func TestValidateAgentEndpointAllowsLocalhostByDefault(t *testing.T) {
	t.Setenv("AGENT_ENDPOINT_ALLOW_PRIVATE", "")
	if err := ValidateAgentEndpoint("http://127.0.0.1:8011"); err != nil {
		t.Fatalf("localhost should be allowed by default: %v", err)
	}
}

func TestValidateAgentEndpointRejectsPrivateWhenDisabled(t *testing.T) {
	t.Setenv("AGENT_ENDPOINT_ALLOW_PRIVATE", "0")
	if err := ValidateAgentEndpoint("http://127.0.0.1:8011"); err == nil {
		t.Fatal("expected private endpoint rejection")
	}
}

func TestValidateAgentEndpointRejectsBadScheme(t *testing.T) {
	if err := ValidateAgentEndpoint("file:///etc/passwd"); err == nil {
		t.Fatal("expected scheme rejection")
	}
}
