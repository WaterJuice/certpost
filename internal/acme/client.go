// ---------------------------------------------------------------------------------------
//
//	client.go
//	---------
//
//	ACME v2 client for Let's Encrypt certificate issuance using DNS-01
//	challenges. Uses net/http for HTTP and native Go crypto for all
//	cryptographic operations.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package acme

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/WaterJuice/certpost/internal/cryptoutil"
	"github.com/WaterJuice/certpost/internal/dns"
	"github.com/WaterJuice/certpost/internal/logbuf"
	"github.com/WaterJuice/certpost/internal/storage"
)

const (
	dnsPropagationWait    = 30 * time.Second
	challengePollInterval = 2 * time.Second
	challengePollTimeout  = 120 * time.Second
	orderPollInterval     = 2 * time.Second
	orderPollTimeout      = 120 * time.Second
	acmeDirectory         = "https://acme-v02.api.letsencrypt.org/directory"
)

// Client is an ACME v2 client for Let's Encrypt.
type Client struct {
	storage       *storage.Storage
	dns           dns.Provider
	directory     map[string]any
	accountKeyPEM string
	accountKID    string
	httpClient    *http.Client
}

// NewClient creates a new ACME client.
func NewClient(s *storage.Storage, d dns.Provider) *Client {
	return &Client{
		storage:    s,
		dns:        d,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

func (c *Client) log(msg string) {
	logbuf.Log("acme", msg)
}

func (c *Client) fetchDirectory() error {
	resp, err := c.httpClient.Get(acmeDirectory)
	if err != nil {
		return fmt.Errorf("fetch ACME directory: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	return json.Unmarshal(body, &c.directory)
}

func (c *Client) getNonce() (string, error) {
	nonceURL, _ := c.directory["newNonce"].(string)
	if nonceURL == "" {
		return "", fmt.Errorf("ACME directory missing newNonce URL")
	}
	req, err := http.NewRequest("HEAD", nonceURL, nil)
	if err != nil {
		return "", fmt.Errorf("build nonce request: %w", err)
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	resp.Body.Close()
	return resp.Header.Get("Replay-Nonce"), nil
}

func (c *Client) acmeRequest(url string, payload any) (map[string]any, http.Header, error) {
	nonce, err := c.getNonce()
	if err != nil {
		return nil, nil, fmt.Errorf("get nonce: %w", err)
	}

	kid := c.accountKID
	body, err := cryptoutil.BuildJWS(url, payload, nonce, c.accountKeyPEM, kid)
	if err != nil {
		return nil, nil, fmt.Errorf("build JWS: %w", err)
	}

	req, err := http.NewRequest("POST", url, strings.NewReader(body))
	if err != nil {
		return nil, nil, fmt.Errorf("build ACME request: %w", err)
	}
	req.Header.Set("Content-Type", "application/jose+json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		return nil, nil, fmt.Errorf("ACME request failed (%d): %s", resp.StatusCode, string(respBody))
	}

	var result map[string]any
	if len(respBody) > 0 {
		_ = json.Unmarshal(respBody, &result)
	}
	return result, resp.Header, nil
}

func (c *Client) ensureAccount() error {
	account, err := c.storage.GetAcmeAccount()
	if err != nil {
		return err
	}

	if account != nil {
		keyPEM, _ := account["key_pem"].(string)
		kid, _ := account["kid"].(string)
		if keyPEM != "" && kid != "" {
			c.accountKeyPEM = keyPEM
			c.accountKID = kid
			return nil
		}
		if keyPEM != "" {
			c.accountKeyPEM = keyPEM
		}
	}

	// Generate account key if needed
	if c.accountKeyPEM == "" {
		c.log("Generating ACME account key...")
		keyPEM, err := cryptoutil.GenerateRSAKey(4096)
		if err != nil {
			return err
		}
		c.accountKeyPEM = keyPEM
	}

	// Register account
	c.log("Registering ACME account...")
	newAccountURL, _ := c.directory["newAccount"].(string)
	_, headers, err := c.acmeRequest(newAccountURL, map[string]any{
		"termsOfServiceAgreed": true,
	})
	if err != nil {
		return fmt.Errorf("ACME registration: %w", err)
	}

	c.accountKID = headers.Get("Location")
	if c.accountKID == "" {
		return fmt.Errorf("ACME registration did not return account URL")
	}

	err = c.storage.SaveAcmeAccount(map[string]any{
		"key_pem": c.accountKeyPEM,
		"kid":     c.accountKID,
	})
	if err != nil {
		return err
	}
	c.log(fmt.Sprintf("Account registered: %s", c.accountKID))
	return nil
}

// Initialise fetches the ACME directory and ensures an account exists.
func (c *Client) Initialise() error {
	if err := c.fetchDirectory(); err != nil {
		return err
	}
	return c.ensureAccount()
}

// IssueCertificate issues a certificate for the given FQDN.
func (c *Client) IssueCertificate(fqdn string) error {
	// Re-fetch directory to ensure URLs are current
	if err := c.fetchDirectory(); err != nil {
		return fmt.Errorf("refresh ACME directory: %w", err)
	}

	c.log(fmt.Sprintf("Ordering certificate for %s...", fqdn))

	// Create order
	newOrderURL, _ := c.directory["newOrder"].(string)
	order, orderHeaders, err := c.acmeRequest(newOrderURL, map[string]any{
		"identifiers": []map[string]string{{"type": "dns", "value": fqdn}},
	})
	if err != nil {
		return fmt.Errorf("create order: %w", err)
	}
	orderURL := orderHeaders.Get("Location")

	// Process authorisations
	auths, _ := order["authorizations"].([]any)
	for _, authURLRaw := range auths {
		authURL, _ := authURLRaw.(string)
		authBody, _, err := c.acmeRequest(authURL, nil)
		if err != nil {
			return fmt.Errorf("get authorisation: %w", err)
		}

		challenges, _ := authBody["challenges"].([]any)
		var dnsChallenge map[string]any
		for _, ch := range challenges {
			chMap, _ := ch.(map[string]any)
			if chMap["type"] == "dns-01" {
				dnsChallenge = chMap
				break
			}
		}
		if dnsChallenge == nil {
			return fmt.Errorf("no DNS-01 challenge found for %s", fqdn)
		}

		token, _ := dnsChallenge["token"].(string)
		challengeURL, _ := dnsChallenge["url"].(string)
		challengeValue, err := cryptoutil.DNSChallengeValue(token, c.accountKeyPEM)
		if err != nil {
			return err
		}

		// Set DNS TXT record
		acmeRecordName := "_acme-challenge." + fqdn
		c.log(fmt.Sprintf("Setting TXT record: %s = %s", acmeRecordName, challengeValue))
		if _, err := c.dns.SetTXTRecord(acmeRecordName, challengeValue); err != nil {
			return fmt.Errorf("set TXT record: %w", err)
		}

		// Wait for DNS propagation
		c.log(fmt.Sprintf("Waiting %ds for DNS propagation...", int(dnsPropagationWait.Seconds())))
		time.Sleep(dnsPropagationWait)

		// Tell ACME server to validate
		c.log("Requesting challenge validation...")
		if _, _, err := c.acmeRequest(challengeURL, map[string]any{}); err != nil {
			return fmt.Errorf("challenge validation request: %w", err)
		}

		// Poll for challenge completion
		deadline := time.Now().Add(challengePollTimeout)
		for time.Now().Before(deadline) {
			authBody, _, err = c.acmeRequest(authURL, nil)
			if err != nil {
				return err
			}
			status, _ := authBody["status"].(string)
			if status == "valid" {
				c.log("Challenge validated!")
				break
			}
			if status == "invalid" {
				return fmt.Errorf("challenge failed for %s: %v", fqdn, authBody)
			}
			time.Sleep(challengePollInterval)
		}
		if status, _ := authBody["status"].(string); status != "valid" {
			return fmt.Errorf("challenge timed out for %s", fqdn)
		}

		// Clean up DNS record
		c.log("Cleaning up TXT record...")
		_ = c.dns.RemoveTXTRecord(acmeRecordName)
	}

	// Generate cert key and CSR
	c.log("Generating certificate key and CSR...")
	certKeyPEM, err := cryptoutil.GenerateRSAKey(2048)
	if err != nil {
		return err
	}
	csrDER, err := cryptoutil.CreateCSR(certKeyPEM, []string{fqdn})
	if err != nil {
		return err
	}
	csrB64 := cryptoutil.B64URL(csrDER)

	// Finalise order
	finaliseURL, _ := order["finalize"].(string)
	c.log("Finalising order...")
	if _, _, err := c.acmeRequest(finaliseURL, map[string]any{"csr": csrB64}); err != nil {
		return fmt.Errorf("finalise order: %w", err)
	}

	// Poll for certificate
	var certURL string
	deadline := time.Now().Add(orderPollTimeout)
	for time.Now().Before(deadline) {
		orderBody, _, err := c.acmeRequest(orderURL, nil)
		if err != nil {
			return err
		}
		status, _ := orderBody["status"].(string)
		if status == "valid" {
			certURL, _ = orderBody["certificate"].(string)
			break
		}
		if status == "invalid" {
			return fmt.Errorf("order failed for %s: %v", fqdn, orderBody)
		}
		time.Sleep(orderPollInterval)
	}
	if certURL == "" {
		return fmt.Errorf("order timed out for %s", fqdn)
	}

	// Download certificate
	c.log("Downloading certificate...")
	nonce, _ := c.getNonce()
	body, err := cryptoutil.BuildJWS(certURL, nil, nonce, c.accountKeyPEM, c.accountKID)
	if err != nil {
		return err
	}
	req, err := http.NewRequest("POST", certURL, strings.NewReader(body))
	if err != nil {
		return fmt.Errorf("build cert download request: %w", err)
	}
	req.Header.Set("Content-Type", "application/jose+json")
	req.Header.Set("Accept", "application/pem-certificate-chain")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		errBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("certificate download failed (%d): %s", resp.StatusCode, string(errBody))
	}

	fullChainBytes, _ := io.ReadAll(resp.Body)
	fullChain := string(fullChainBytes)

	// Split into cert and chain
	parts := strings.SplitN(fullChain, "-----END CERTIFICATE-----", 2)
	certPEM := ""
	chainPEM := ""
	if len(parts) >= 1 {
		certPEM = parts[0] + "-----END CERTIFICATE-----\n"
	}
	if len(parts) >= 2 {
		chainPEM = strings.TrimSpace(parts[1])
		if chainPEM != "" && !strings.HasSuffix(chainPEM, "\n") {
			chainPEM += "\n"
		}
	}

	// Parse expiry
	expiresAt, err := cryptoutil.ParseCertExpiry(certPEM)
	if err != nil {
		return fmt.Errorf("parse cert expiry: %w", err)
	}

	// Save
	if err := c.storage.SaveCert(fqdn, certPEM, chainPEM, certKeyPEM, expiresAt); err != nil {
		return err
	}
	if err := c.storage.UpdateDomain(fqdn, map[string]any{
		"status":          "issued",
		"cert_expires_at": expiresAt,
		"last_error":      nil,
	}); err != nil {
		return err
	}

	c.log(fmt.Sprintf("Certificate issued for %s", fqdn))
	return nil
}
