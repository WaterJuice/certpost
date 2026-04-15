// ---------------------------------------------------------------------------------------
//
//	factory.go
//	----------
//
//	DNS provider factory. Creates the appropriate Provider implementation from
//	a configuration map. Supports "cloudflare" and "technitium" providers.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package dns

import "fmt"

// CreateProvider creates a DNS provider from a configuration map.
// The map must have a "provider" key set to "cloudflare", "technitium",
// or "demo" (a no-op stub for local preview).
func CreateProvider(config map[string]any) (Provider, error) {
	providerName, _ := config["provider"].(string)
	if providerName == "" {
		return nil, fmt.Errorf("DNS provider config missing 'provider' key")
	}

	switch providerName {
	case "demo":
		return &demoProvider{}, nil

	case "cloudflare":
		apiToken, _ := config["api_token"].(string)
		zoneID, _ := config["zone_id"].(string)
		if apiToken == "" || zoneID == "" {
			return nil, fmt.Errorf("Cloudflare provider requires 'api_token' and 'zone_id'")
		}
		return NewCloudflareClient(apiToken, zoneID), nil

	case "technitium":
		serverURL, _ := config["server_url"].(string)
		apiToken, _ := config["api_token"].(string)
		zone, _ := config["zone"].(string)
		if serverURL == "" || apiToken == "" || zone == "" {
			return nil, fmt.Errorf("Technitium provider requires 'server_url', 'api_token', and 'zone'")
		}
		return NewTechnitiumClient(serverURL, apiToken, zone), nil

	default:
		return nil, fmt.Errorf("unknown DNS provider: %q (supported: cloudflare, technitium)", providerName)
	}
}
