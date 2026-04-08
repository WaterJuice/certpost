// ---------------------------------------------------------------------------------------
//
//	fetch.go
//	--------
//
//	Certificate fetching and saving logic shared between the client CLI and
//	proxy. Fetches certificates from a certpost server via the API and saves
//	them as PEM files.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package client

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// CertData holds certificate data from the server.
type CertData struct {
	CertPEM   string `json:"cert_pem"`
	ChainPEM  string `json:"chain_pem"`
	KeyPEM    string `json:"key_pem"`
	ExpiresAt string `json:"expires_at"`
	IssuedAt  string `json:"issued_at"`
}

var httpClient = &http.Client{Timeout: 30 * time.Second}

// FetchCert fetches certificate data from a certpost server.
func FetchCert(serverURL, token, domain string) (*CertData, error) {
	url := fmt.Sprintf("%s/api/cert/%s", serverURL, domain)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("invalid server URL: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("could not connect to server: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("server returned %d: %s", resp.StatusCode, string(body))
	}

	var data CertData
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, fmt.Errorf("invalid response: %w", err)
	}
	return &data, nil
}

// SaveCert saves certificate files to disk.
func SaveCert(outputDir, domain string, data *CertData) error {
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return err
	}

	certPath := filepath.Join(outputDir, domain+".crt")
	keyPath := filepath.Join(outputDir, domain+".key")

	if err := os.WriteFile(certPath, []byte(data.CertPEM+data.ChainPEM), 0o644); err != nil {
		return err
	}
	if err := os.WriteFile(keyPath, []byte(data.KeyPEM), 0o600); err != nil {
		return err
	}

	fmt.Printf("Wrote public cert to %s\n", certPath)
	fmt.Printf("Wrote private key to %s\n", keyPath)
	return nil
}

// ResolveTokenDomain asks the server which domain a token belongs to.
func ResolveTokenDomain(serverURL, token string) string {
	if serverURL == "" {
		return ""
	}
	url := fmt.Sprintf("%s/api/token-info", serverURL)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return ""
	}
	req.Header.Set("Authorization", "Bearer "+token)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	var result map[string]string
	if json.Unmarshal(body, &result) == nil {
		return result["domain"]
	}
	return ""
}
