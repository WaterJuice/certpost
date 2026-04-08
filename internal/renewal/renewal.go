// ---------------------------------------------------------------------------------------
//
//	renewal.go
//	----------
//
//	Background certificate renewal goroutine. Checks daily, proactively renews
//	the 2 oldest certs per cycle to keep them fresh, with a 30-day expiry
//	safety net for forced renewal.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package renewal

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/WaterJuice/certpost/internal/acme"
	"github.com/WaterJuice/certpost/internal/logbuf"
	"github.com/WaterJuice/certpost/internal/storage"
)

const (
	checkInterval     = 24 * time.Hour
	renewalWindow     = 30 * 24 * time.Hour // 30 days before expiry (forced renewal)
	dailyRenewalLimit = 2                   // max certs to proactively renew per cycle
)

// Start starts the renewal goroutine. Cancel the context to stop it.
func Start(ctx context.Context, s *storage.Storage, acmeClient *acme.Client) {
	go run(ctx, s, acmeClient)
}

func run(ctx context.Context, s *storage.Storage, acmeClient *acme.Client) {
	// Initial delay to let the server start up
	select {
	case <-time.After(10 * time.Second):
	case <-ctx.Done():
		return
	}

	for {
		checkRenewals(s, acmeClient)

		select {
		case <-time.After(checkInterval):
		case <-ctx.Done():
			return
		}
	}
}

type renewalCandidate struct {
	timeRemaining float64
	subdomain     string
}

func checkRenewals(s *storage.Storage, acmeClient *acme.Client) {
	defer func() {
		if r := recover(); r != nil {
			logbuf.Log("renewal", fmt.Sprintf("Error during renewal check: %v", r))
		}
	}()

	domains, err := s.GetDomains()
	if err != nil {
		logbuf.Log("renewal", fmt.Sprintf("Error reading domains: %v", err))
		return
	}

	now := time.Now().UTC()
	var proactiveCandidates []renewalCandidate

	for _, domain := range domains {
		subdomain, _ := domain["subdomain"].(string)
		status, _ := domain["status"].(string)
		expiresAtStr, _ := domain["cert_expires_at"].(string)

		if subdomain == "" {
			continue
		}

		// Issue certs for pending domains
		if status == "pending" {
			issueCert(s, acmeClient, subdomain)
			continue
		}

		// Force-renew certs within the expiry window (safety net)
		if status == "issued" && expiresAtStr != "" {
			expiresAt, err := time.Parse(time.RFC3339, expiresAtStr)
			if err != nil {
				continue
			}
			timeRemaining := expiresAt.Sub(now)
			if timeRemaining < renewalWindow {
				daysLeft := timeRemaining.Hours() / 24
				logbuf.Log("renewal", fmt.Sprintf(
					"Certificate for %s expires in %.0f days, renewing...", subdomain, daysLeft))
				issueCert(s, acmeClient, subdomain)
			} else {
				proactiveCandidates = append(proactiveCandidates, renewalCandidate{
					timeRemaining: timeRemaining.Seconds(),
					subdomain:     subdomain,
				})
			}
		}
	}

	// Proactively renew the oldest certs (earliest expiry first)
	sort.Slice(proactiveCandidates, func(i, j int) bool {
		return proactiveCandidates[i].timeRemaining < proactiveCandidates[j].timeRemaining
	})

	renewed := 0
	for _, c := range proactiveCandidates {
		if renewed >= dailyRenewalLimit {
			break
		}
		daysUntil := c.timeRemaining / 86400
		logbuf.Log("renewal", fmt.Sprintf(
			"Proactive renewal for %s (expires in %.0f days)", c.subdomain, daysUntil))
		issueCert(s, acmeClient, c.subdomain)
		renewed++
	}
}

func issueCert(s *storage.Storage, acmeClient *acme.Client, subdomain string) {
	_ = s.UpdateDomain(subdomain, map[string]any{"status": "issuing"})
	if err := acmeClient.IssueCertificate(subdomain); err != nil {
		errMsg := fmt.Sprintf("%v", err)
		logbuf.Log("renewal", fmt.Sprintf("Failed to issue cert for %s: %s", subdomain, errMsg))
		_ = s.UpdateDomain(subdomain, map[string]any{
			"status":     "error",
			"last_error": errMsg,
		})
	}
}
