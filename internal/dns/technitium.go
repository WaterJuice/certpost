// ---------------------------------------------------------------------------------------
//
//	technitium.go
//	-------------
//
//	Technitium DNS Server API client for managing DNS records. Handles TXT records
//	for DNS-01 ACME challenges and A/CNAME records for subdomain pointing.
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
	"net/url"
	"strings"
	"time"
)

// TechnitiumClient implements Provider for the Technitium DNS Server API.
type TechnitiumClient struct {
	serverURL string
	apiToken  string
	zone      string
	client    *http.Client
}

// NewTechnitiumClient creates a new Technitium DNS client.
func NewTechnitiumClient(serverURL, apiToken, zone string) *TechnitiumClient {
	return &TechnitiumClient{
		serverURL: strings.TrimRight(serverURL, "/"),
		apiToken:  apiToken,
		zone:      zone,
		client:    &http.Client{Timeout: 30 * time.Second},
	}
}

func (t *TechnitiumClient) apiCall(endpoint string, params map[string]string) (map[string]any, error) {
	params["token"] = t.apiToken
	query := url.Values{}
	for k, v := range params {
		query.Set(k, v)
	}
	reqURL := fmt.Sprintf("%s%s?%s", t.serverURL, endpoint, query.Encode())

	resp, err := t.client.Get(reqURL)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("Technitium API error (%d): %s", resp.StatusCode, string(body))
	}

	var result map[string]any
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}

	if status, _ := result["status"].(string); status != "ok" {
		errMsg, _ := result["errorMessage"].(string)
		if errMsg == "" {
			errMsg = "Unknown error"
		}
		return nil, fmt.Errorf("Technitium API error: %s", errMsg)
	}

	return result, nil
}

func (t *TechnitiumClient) findRecords(name, recordType string) []map[string]any {
	result, err := t.apiCall("/api/zones/records/get", map[string]string{
		"domain": name,
		"zone":   t.zone,
	})
	if err != nil {
		return nil
	}

	response, _ := result["response"].(map[string]any)
	records, _ := response["records"].([]any)
	var out []map[string]any
	for _, r := range records {
		rm, ok := r.(map[string]any)
		if !ok {
			continue
		}
		if rm["type"] == recordType && rm["name"] == name {
			out = append(out, rm)
		}
	}
	return out
}

func (t *TechnitiumClient) SetTXTRecord(name, value string) (string, error) {
	_ = t.RemoveTXTRecord(name)
	_, err := t.apiCall("/api/zones/records/add", map[string]string{
		"domain": name,
		"zone":   t.zone,
		"type":   "TXT",
		"ttl":    "60",
		"text":   value,
	})
	return name, err
}

func (t *TechnitiumClient) RemoveTXTRecord(name string) error {
	records := t.findRecords(name, "TXT")
	for _, r := range records {
		rData, _ := r["rData"].(map[string]any)
		text, _ := rData["text"].(string)
		_, _ = t.apiCall("/api/zones/records/delete", map[string]string{
			"domain": name,
			"zone":   t.zone,
			"type":   "TXT",
			"text":   text,
		})
	}
	return nil
}

func (t *TechnitiumClient) SetARecord(name, ip string) (string, error) {
	_ = t.RemoveARecord(name)
	_, err := t.apiCall("/api/zones/records/add", map[string]string{
		"domain":    name,
		"zone":      t.zone,
		"type":      "A",
		"ttl":       "300",
		"ipAddress": ip,
	})
	return name, err
}

func (t *TechnitiumClient) RemoveARecord(name string) error {
	records := t.findRecords(name, "A")
	for _, r := range records {
		rData, _ := r["rData"].(map[string]any)
		ip, _ := rData["ipAddress"].(string)
		_, _ = t.apiCall("/api/zones/records/delete", map[string]string{
			"domain":    name,
			"zone":      t.zone,
			"type":      "A",
			"ipAddress": ip,
		})
	}
	return nil
}

func (t *TechnitiumClient) SetCNAMERecord(name, target string) (string, error) {
	_ = t.RemoveCNAMERecord(name)
	_, err := t.apiCall("/api/zones/records/add", map[string]string{
		"domain": name,
		"zone":   t.zone,
		"type":   "CNAME",
		"ttl":    "300",
		"cname":  target,
	})
	return name, err
}

func (t *TechnitiumClient) RemoveCNAMERecord(name string) error {
	records := t.findRecords(name, "CNAME")
	for _, r := range records {
		rData, _ := r["rData"].(map[string]any)
		cname, _ := rData["cname"].(string)
		_, _ = t.apiCall("/api/zones/records/delete", map[string]string{
			"domain": name,
			"zone":   t.zone,
			"type":   "CNAME",
			"cname":  cname,
		})
	}
	return nil
}
