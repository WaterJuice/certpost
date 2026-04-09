// ---------------------------------------------------------------------------------------
//
//	cloudflare.go
//	-------------
//
//	Cloudflare DNS API client for managing DNS records. Handles TXT records for
//	DNS-01 ACME challenges and A/CNAME records for subdomain pointing.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package dns

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

const cloudflareAPIBase = "https://api.cloudflare.com/client/v4"

// CloudflareClient implements Provider for the Cloudflare DNS API.
type CloudflareClient struct {
	apiToken string
	zoneID   string
	client   *http.Client
}

// NewCloudflareClient creates a new Cloudflare DNS client.
func NewCloudflareClient(apiToken, zoneID string) *CloudflareClient {
	return &CloudflareClient{
		apiToken: apiToken,
		zoneID:   zoneID,
		client:   &http.Client{Timeout: 30 * time.Second},
	}
}

func (c *CloudflareClient) apiCall(method, path string, body any) (map[string]any, error) {
	url := cloudflareAPIBase + path
	var bodyReader io.Reader
	if body != nil {
		data, _ := json.Marshal(body)
		bodyReader = strings.NewReader(string(data))
	}

	req, err := http.NewRequest(method, url, bodyReader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+c.apiToken)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("Cloudflare API error (%d): %s", resp.StatusCode, string(respBody))
	}

	var result map[string]any
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, err
	}

	if success, _ := result["success"].(bool); !success {
		errors, _ := result["errors"].([]any)
		var msgs []string
		for _, e := range errors {
			if em, ok := e.(map[string]any); ok {
				msgs = append(msgs, fmt.Sprintf("%v", em["message"]))
			}
		}
		return nil, fmt.Errorf("Cloudflare API error: %s", strings.Join(msgs, "; "))
	}

	return result, nil
}

func (c *CloudflareClient) findRecords(name, recordType string) ([]map[string]any, error) {
	path := fmt.Sprintf("/zones/%s/dns_records?type=%s&name=%s", c.zoneID, recordType, name)
	result, err := c.apiCall("GET", path, nil)
	if err != nil {
		return nil, err
	}
	records, _ := result["result"].([]any)
	var out []map[string]any
	for _, r := range records {
		if rm, ok := r.(map[string]any); ok {
			out = append(out, rm)
		}
	}
	return out, nil
}

func (c *CloudflareClient) deleteRecords(name, recordType string) error {
	records, err := c.findRecords(name, recordType)
	if err != nil {
		return err
	}
	for _, r := range records {
		id, _ := r["id"].(string)
		if id != "" {
			_, _ = c.apiCall("DELETE", fmt.Sprintf("/zones/%s/dns_records/%s", c.zoneID, id), nil)
		}
	}
	return nil
}

func (c *CloudflareClient) setRecord(recordType string, body map[string]any) (string, error) {
	name, _ := body["name"].(string)
	_ = c.deleteRecords(name, recordType)
	body["type"] = recordType
	result, err := c.apiCall("POST", fmt.Sprintf("/zones/%s/dns_records", c.zoneID), body)
	if err != nil {
		return "", err
	}
	rec, _ := result["result"].(map[string]any)
	id, _ := rec["id"].(string)
	return id, nil
}

func (c *CloudflareClient) SetTXTRecord(name, value string) (string, error) {
	return c.setRecord("TXT", map[string]any{"name": name, "content": value, "ttl": 60})
}

func (c *CloudflareClient) RemoveTXTRecord(name string) error {
	return c.deleteRecords(name, "TXT")
}

func (c *CloudflareClient) SetARecord(name, ip string) (string, error) {
	return c.setRecord("A", map[string]any{"name": name, "content": ip, "ttl": 1, "proxied": false})
}

func (c *CloudflareClient) RemoveARecord(name string) error {
	return c.deleteRecords(name, "A")
}

func (c *CloudflareClient) SetCNAMERecord(name, target string) (string, error) {
	return c.setRecord("CNAME", map[string]any{"name": name, "content": target, "ttl": 1, "proxied": false})
}

func (c *CloudflareClient) RemoveCNAMERecord(name string) error {
	return c.deleteRecords(name, "CNAME")
}
