// ---------------------------------------------------------------------------------------
//
//	spec.go
//	-------
//
//	OpenAPI 3.0 specification and human-readable help text for the certpost API.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package server

var apiHelpText = `certpost API
============

GET /api/version
  Returns product name, API version, and server version.
  No authentication required.

GET /api/spec
  Returns the OpenAPI 3.0 specification as JSON.
  No authentication required.

GET /api/help
  This help text.
  No authentication required.

GET /api/token-info
  Returns the domain associated with a bearer token.
  Requires a bearer token in the Authorization header.

  Header:  Authorization: Bearer <token>

  Response:
    domain         - The domain this token is for

GET /api/cert/<domain>
  Returns the certificate, chain, and private key for a domain.
  Requires a domain-specific bearer token in the Authorization header.

  Header:  Authorization: Bearer <token>

  Response:
    cert_pem       - Server certificate (PEM)
    chain_pem      - Intermediate certificate chain (PEM)
    key_pem        - Private key (PEM)
    expires_at     - Certificate expiry (ISO 8601)
    issued_at      - Certificate issue date (ISO 8601)

  Example:
    curl -H "Authorization: Bearer <token>" http://localhost:8443/api/cert/app.example.com
`

var openAPISpec = map[string]any{
	"openapi": "3.0.3",
	"info": map[string]any{
		"title":       "certpost",
		"description": "Let's Encrypt certificate manager API",
		"version":     "1.0",
	},
	"paths": map[string]any{
		"/api/version": map[string]any{
			"get": map[string]any{
				"summary": "Server version information",
				"responses": map[string]any{
					"200": map[string]any{
						"description": "Version info",
						"content": map[string]any{
							"application/json": map[string]any{
								"schema": map[string]any{
									"type": "object",
									"properties": map[string]any{
										"product":        map[string]string{"type": "string", "example": "certpost"},
										"api_version":    map[string]string{"type": "string", "example": "1.0"},
										"server_version": map[string]string{"type": "string", "example": "1.0.0"},
									},
								},
							},
						},
					},
				},
			},
		},
		"/api/help": map[string]any{
			"get": map[string]any{
				"summary": "Human-readable API help",
				"responses": map[string]any{
					"200": map[string]any{
						"description": "Plain text help",
						"content": map[string]any{
							"text/plain": map[string]any{
								"schema": map[string]string{"type": "string"},
							},
						},
					},
				},
			},
		},
		"/api/cert/{domain}": map[string]any{
			"get": map[string]any{
				"summary": "Retrieve certificate for a domain",
				"parameters": []map[string]any{
					{
						"name":        "domain",
						"in":          "path",
						"required":    true,
						"schema":      map[string]string{"type": "string"},
						"description": "Fully qualified domain name",
					},
				},
				"security": []map[string][]string{{"bearerAuth": {}}},
				"responses": map[string]any{
					"200": map[string]any{
						"description": "Certificate data",
						"content": map[string]any{
							"application/json": map[string]any{
								"schema": map[string]any{
									"type": "object",
									"properties": map[string]any{
										"cert_pem":   map[string]string{"type": "string", "description": "Server certificate (PEM)"},
										"chain_pem":  map[string]string{"type": "string", "description": "Intermediate chain (PEM)"},
										"key_pem":    map[string]string{"type": "string", "description": "Private key (PEM)"},
										"expires_at": map[string]string{"type": "string", "format": "date-time", "description": "Certificate expiry"},
										"issued_at":  map[string]string{"type": "string", "format": "date-time", "description": "Certificate issue date"},
									},
								},
							},
						},
					},
					"401": map[string]string{"description": "Missing or invalid Authorization header"},
					"403": map[string]string{"description": "Invalid token for this domain"},
					"404": map[string]string{"description": "No certificate found for domain"},
				},
			},
		},
	},
	"components": map[string]any{
		"securitySchemes": map[string]any{
			"bearerAuth": map[string]string{
				"type":        "http",
				"scheme":      "bearer",
				"description": "Domain-specific API token from the certpost admin panel",
			},
		},
	},
}
