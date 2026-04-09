// ---------------------------------------------------------------------------------------
//
//	storage.go
//	----------
//
//	JSON file storage for certpost. Manages configuration, certificates, and
//	per-domain API tokens. All file writes are protected by a mutex and use
//	atomic temp-file + rename.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package storage

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const (
	tokenChars  = "abcdefghijklmnopqrstuvwxyz0123456789"
	tokenLength = 40
)

// Storage manages JSON file storage for certpost data.
type Storage struct {
	dataDir string
	mu      sync.Mutex
}

// New creates a new Storage instance and initialises the data directory.
func New(dataDir string) (*Storage, error) {
	s := &Storage{dataDir: dataDir}
	if err := s.initialise(); err != nil {
		return nil, err
	}
	return s, nil
}

// DataDir returns the data directory path.
func (s *Storage) DataDir() string {
	return s.dataDir
}

func (s *Storage) initialise() error {
	if err := os.MkdirAll(s.dataDir, 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Join(s.dataDir, "certs"), 0o755); err != nil {
		return err
	}

	configPath := filepath.Join(s.dataDir, "config.json")
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		adminKey := GenerateToken()
		defaultConfig := map[string]any{
			"base_domain": "",
			"admin_key":   adminKey,
			"port":        8443,
			"dns": map[string]any{
				"provider":  "cloudflare",
				"api_token": "",
				"zone_id":   "",
			},
		}
		if err := s.writeJSON(configPath, defaultConfig); err != nil {
			return err
		}
	}

	domainsPath := filepath.Join(s.dataDir, "domains.json")
	if _, err := os.Stat(domainsPath); os.IsNotExist(err) {
		if err := s.writeJSON(domainsPath, map[string]any{"domains": []any{}}); err != nil {
			return err
		}
	}
	return nil
}

func (s *Storage) readJSON(path string) (map[string]any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, err
	}
	return result, nil
}

func (s *Storage) writeJSON(path string, data any) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return writeJSONUnlocked(path, data)
}

func writeJSONUnlocked(path string, data any) error {
	out, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return err
	}
	out = append(out, '\n')
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, out, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// --- Config ---

// GetConfig reads the configuration file. Automatically migrates legacy
// flat Cloudflare configs to the new provider format.
func (s *Storage) GetConfig() (map[string]any, error) {
	config, err := s.readJSON(filepath.Join(s.dataDir, "config.json"))
	if err != nil {
		return nil, err
	}
	if _, hasLegacy := config["cloudflare_api_token"]; hasLegacy {
		if _, hasNew := config["dns"]; !hasNew {
			config = s.migrateLegacyConfig(config)
		}
	}
	return config, nil
}

// SaveConfig writes the configuration file.
func (s *Storage) SaveConfig(config map[string]any) error {
	return s.writeJSON(filepath.Join(s.dataDir, "config.json"), config)
}

func (s *Storage) migrateLegacyConfig(config map[string]any) map[string]any {
	apiToken, _ := config["cloudflare_api_token"].(string)
	zoneID, _ := config["cloudflare_zone_id"].(string)
	delete(config, "cloudflare_api_token")
	delete(config, "cloudflare_zone_id")
	config["dns"] = map[string]any{
		"provider":  "cloudflare",
		"api_token": apiToken,
		"zone_id":   zoneID,
	}
	_ = s.writeJSON(filepath.Join(s.dataDir, "config.json"), config)
	return config
}

// --- Admin auth ---

// VerifyAdminKey verifies the admin login key.
func (s *Storage) VerifyAdminKey(key string) bool {
	config, err := s.GetConfig()
	if err != nil {
		return false
	}
	adminKey, _ := config["admin_key"].(string)
	return key == adminKey
}

// AdminCookieValue returns a SHA-256 hash of the admin key for use as a session cookie.
func (s *Storage) AdminCookieValue() string {
	config, err := s.GetConfig()
	if err != nil {
		return ""
	}
	adminKey, _ := config["admin_key"].(string)
	hash := sha256.Sum256([]byte(adminKey))
	return fmt.Sprintf("%x", hash)
}

// VerifyAdminCookie verifies an admin session cookie value.
func (s *Storage) VerifyAdminCookie(value string) bool {
	return value == s.AdminCookieValue()
}

// --- Domains ---

// GetDomains returns the list of managed domains.
func (s *Storage) GetDomains() ([]map[string]any, error) {
	data, err := s.readJSON(filepath.Join(s.dataDir, "domains.json"))
	if err != nil {
		return nil, err
	}
	domains, _ := data["domains"].([]any)
	result := make([]map[string]any, 0, len(domains))
	for _, d := range domains {
		if dm, ok := d.(map[string]any); ok {
			result = append(result, dm)
		}
	}
	return result, nil
}

// AddDomain adds a new subdomain with a generated API token. Returns the domain entry.
func (s *Storage) AddDomain(subdomain, target string) (map[string]any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path := filepath.Join(s.dataDir, "domains.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var file map[string]any
	if err := json.Unmarshal(data, &file); err != nil {
		return nil, err
	}
	domains, _ := file["domains"].([]any)

	// Check for duplicates
	for _, d := range domains {
		if dm, ok := d.(map[string]any); ok {
			if dm["subdomain"] == subdomain {
				return dm, nil
			}
		}
	}

	entry := map[string]any{
		"subdomain":       subdomain,
		"target":          target,
		"status":          "pending",
		"api_token":       GenerateToken(),
		"added_at":        time.Now().UTC().Format(time.RFC3339),
		"cert_expires_at": nil,
		"last_error":      nil,
	}
	domains = append(domains, entry)
	file["domains"] = domains
	if err := writeJSONUnlocked(path, file); err != nil {
		return nil, err
	}
	return entry, nil
}

// UpdateDomain updates fields on a domain entry.
func (s *Storage) UpdateDomain(subdomain string, updates map[string]any) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path := filepath.Join(s.dataDir, "domains.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var file map[string]any
	if err := json.Unmarshal(data, &file); err != nil {
		return err
	}
	domains, _ := file["domains"].([]any)

	for _, d := range domains {
		if dm, ok := d.(map[string]any); ok {
			if dm["subdomain"] == subdomain {
				for k, v := range updates {
					dm[k] = v
				}
				break
			}
		}
	}

	return writeJSONUnlocked(path, file)
}

// RemoveDomain removes a subdomain from management.
func (s *Storage) RemoveDomain(subdomain string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path := filepath.Join(s.dataDir, "domains.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var file map[string]any
	if err := json.Unmarshal(data, &file); err != nil {
		return err
	}
	domains, _ := file["domains"].([]any)

	var filtered []any
	for _, d := range domains {
		if dm, ok := d.(map[string]any); ok {
			if dm["subdomain"] != subdomain {
				filtered = append(filtered, dm)
			}
		}
	}
	if filtered == nil {
		filtered = []any{}
	}
	file["domains"] = filtered
	return writeJSONUnlocked(path, file)
}

// RotateDomainToken generates a new API token for a domain. Returns the new token.
func (s *Storage) RotateDomainToken(subdomain string) (string, error) {
	newToken := GenerateToken()
	err := s.UpdateDomain(subdomain, map[string]any{"api_token": newToken})
	return newToken, err
}

// VerifyDomainToken verifies an API token against a specific domain.
func (s *Storage) VerifyDomainToken(subdomain, token string) bool {
	domains, err := s.GetDomains()
	if err != nil {
		return false
	}
	for _, d := range domains {
		if d["subdomain"] == subdomain && d["api_token"] == token {
			return true
		}
	}
	return false
}

// --- Certificates ---

// SaveCert saves certificate files for a subdomain.
func (s *Storage) SaveCert(subdomain, certPEM, chainPEM, keyPEM, expiresAt string) error {
	certDir := filepath.Join(s.dataDir, "certs", subdomain)
	if err := os.MkdirAll(certDir, 0o755); err != nil {
		return err
	}

	certData := map[string]any{
		"cert_pem":   certPEM,
		"chain_pem":  chainPEM,
		"key_pem":    keyPEM,
		"expires_at": expiresAt,
		"issued_at":  time.Now().UTC().Format(time.RFC3339),
	}
	return s.writeJSON(filepath.Join(certDir, "cert.json"), certData)
}

// GetCert retrieves certificate data for a subdomain, or nil if not found.
func (s *Storage) GetCert(subdomain string) (map[string]any, error) {
	certPath := filepath.Join(s.dataDir, "certs", subdomain, "cert.json")
	data, err := s.readJSON(certPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	return data, nil
}

// --- ACME Account ---

// GetAcmeAccount retrieves the ACME account data, or nil if not registered.
func (s *Storage) GetAcmeAccount() (map[string]any, error) {
	accountPath := filepath.Join(s.dataDir, "acme_account.json")
	data, err := s.readJSON(accountPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	return data, nil
}

// SaveAcmeAccount saves ACME account registration data.
func (s *Storage) SaveAcmeAccount(data map[string]any) error {
	return s.writeJSON(filepath.Join(s.dataDir, "acme_account.json"), data)
}

// --- Helpers ---

// GenerateToken creates a cryptographically random token string.
func GenerateToken() string {
	b := make([]byte, tokenLength)
	for i := range b {
		n, _ := rand.Int(rand.Reader, big.NewInt(int64(len(tokenChars))))
		b[i] = tokenChars[n.Int64()]
	}
	return string(b)
}
