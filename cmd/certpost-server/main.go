// ---------------------------------------------------------------------------------------
//
//	main.go (certpost-server)
//	-------------------------
//
//	CLI for the certpost server. Subcommands:
//	  run   - Start the HTTP server
//	  setup - Interactive wizard to create config.json
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"github.com/WaterJuice/certpost/internal/server"
	"github.com/WaterJuice/certpost/internal/storage"
	"github.com/WaterJuice/certpost/internal/version"
)

func main() {
	os.Exit(run())
}

func run() int {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "--license", "--licence":
			fmt.Println(version.LicenceText)
			return 0
		case "--version", "-v":
			fmt.Printf("certpost-server: %s\ngo: %s\n", version.Version, strings.TrimPrefix(runtime.Version(), "go"))
			return 0
		}
	}

	if len(os.Args) < 2 {
		printHelp()
		return 0
	}

	switch os.Args[1] {
	case "run":
		return runCmd()
	case "setup":
		return setupCmd()
	case "--help", "-h", "help":
		printHelp()
		return 0
	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n\n", os.Args[1])
		printHelp()
		return 1
	}
}

func printHelp() {
	fmt.Fprintf(os.Stderr, `certpost-server — issues and renews Let's Encrypt certificates via DNS-01,
manages DNS records, and serves certificates via API. Supports Cloudflare
and Technitium DNS providers.

Quick start:
  1. certpost-server setup -d <dir> — create config interactively
  2. certpost-server run -d <dir> — start the server

Commands:
  run     Start the certpost server
  setup   Interactive setup wizard for config.json

Flags:
  --version   Show version and exit
  --license   Show licence information and exit
  --help      Show this help
`)
}

func runCmd() int {
	fs := flag.NewFlagSet("run", flag.ExitOnError)
	dataDir := fs.String("d", "", "Data directory containing config.json (required)")
	fs.StringVar(dataDir, "data-dir", "", "Data directory containing config.json (required)")
	port := fs.Int("p", 8443, "Port to listen on")
	fs.IntVar(port, "port", 8443, "Port to listen on")
	host := fs.String("H", "0.0.0.0", "Host to bind to")
	fs.StringVar(host, "host", "0.0.0.0", "Host to bind to")

	if err := fs.Parse(os.Args[2:]); err != nil {
		return 1
	}

	if *dataDir == "" {
		fmt.Fprintln(os.Stderr, "Error: --data-dir / -d is required")
		return 1
	}

	configPath := filepath.Join(*dataDir, "config.json")
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		fmt.Fprintf(os.Stderr, "No config found at %s\nRun 'certpost-server setup -d %s' to create one.\n", configPath, *dataDir)
		return 1
	}

	// CLI flags override config values
	configData, err := os.ReadFile(configPath)
	if err == nil {
		var config map[string]any
		if json.Unmarshal(configData, &config) == nil {
			if *host == "0.0.0.0" {
				if bind, ok := config["bind"].(string); ok && bind != "" {
					*host = bind
				}
			}
			if *port == 8443 {
				if p, ok := config["port"].(float64); ok {
					*port = int(p)
				}
			}
		}
	}

	fmt.Fprintf(os.Stderr, "certpost-server %s\n", version.Version)
	fmt.Fprintf(os.Stderr, "Serving on http://%s:%d\n", *host, *port)

	if err := server.Run(*host, *port, *dataDir); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}
	return 0
}

func setupCmd() int {
	fs := flag.NewFlagSet("setup", flag.ExitOnError)
	dataDir := fs.String("d", "", "Data directory to create config in (required)")
	fs.StringVar(dataDir, "data-dir", "", "Data directory to create config in (required)")

	if err := fs.Parse(os.Args[2:]); err != nil {
		return 1
	}

	if *dataDir == "" {
		fmt.Fprintln(os.Stderr, "Error: --data-dir / -d is required")
		return 1
	}

	runSetup(*dataDir)
	return 0
}

var scanner = bufio.NewScanner(os.Stdin)

func prompt(label, defaultVal string) string {
	if defaultVal != "" {
		fmt.Printf("  %s [%s]: ", label, defaultVal)
	} else {
		fmt.Printf("  %s: ", label)
	}
	scanner.Scan()
	result := strings.TrimSpace(scanner.Text())
	if result == "" {
		return defaultVal
	}
	return result
}

func promptChoice(label string, options []string, defaultVal string) string {
	optStr := strings.Join(options, "/")
	if defaultVal != "" {
		fmt.Printf("  %s (%s) [%s]: ", label, optStr, defaultVal)
	} else {
		for {
			fmt.Printf("  %s (%s): ", label, optStr)
			scanner.Scan()
			result := strings.TrimSpace(strings.ToLower(scanner.Text()))
			for _, opt := range options {
				if result == opt {
					return result
				}
			}
			fmt.Printf("    Please choose one of: %s\n", optStr)
		}
	}
	scanner.Scan()
	result := strings.TrimSpace(strings.ToLower(scanner.Text()))
	for _, opt := range options {
		if result == opt {
			return result
		}
	}
	return defaultVal
}

func promptProvider(label string, existing map[string]any) map[string]any {
	provider := promptChoice(label+" provider", []string{"cloudflare", "technitium"}, getStr(existing, "provider", "cloudflare"))

	if provider == "cloudflare" {
		apiToken := prompt("Cloudflare API token", getStr(existing, "api_token", ""))
		zoneID := prompt("Cloudflare Zone ID", getStr(existing, "zone_id", ""))
		return map[string]any{"provider": "cloudflare", "api_token": apiToken, "zone_id": zoneID}
	}

	serverURL := prompt("Technitium server URL (e.g. https://dns.example.com)", getStr(existing, "server_url", ""))
	apiToken := prompt("Technitium API token", getStr(existing, "api_token", ""))
	zone := prompt("Technitium zone name (e.g. example.com)", getStr(existing, "zone", ""))
	return map[string]any{"provider": "technitium", "server_url": serverURL, "api_token": apiToken, "zone": zone}
}

func getStr(m map[string]any, key, fallback string) string {
	if v, ok := m[key].(string); ok && v != "" {
		return v
	}
	return fallback
}

func runSetup(dataDir string) {
	os.MkdirAll(dataDir, 0o755)
	os.MkdirAll(filepath.Join(dataDir, "certs"), 0o755)

	configPath := filepath.Join(dataDir, "config.json")

	var existing map[string]any
	if data, err := os.ReadFile(configPath); err == nil {
		json.Unmarshal(data, &existing)
		fmt.Printf("\nUpdating existing config at %s\n", configPath)
	} else {
		existing = map[string]any{}
		fmt.Printf("\nCreating new config at %s\n", configPath)
	}

	fmt.Println("Press Enter to skip any field — you can fill it in later.")
	fmt.Println()

	fmt.Println("Domain settings:")
	baseDomain := prompt("Base domain (e.g. example.com)", getStr(existing, "base_domain", ""))

	// DNS providers
	existingShared, _ := existing["dns"].(map[string]any)
	if existingShared == nil {
		existingShared = map[string]any{}
	}
	existingAcme, _ := existing["dns_acme"].(map[string]any)
	if existingAcme == nil {
		existingAcme = existingShared
	}
	existingRecords, _ := existing["dns_records"].(map[string]any)
	if existingRecords == nil {
		existingRecords = existingShared
	}

	fmt.Println("\nDNS provider for ACME challenges (TXT records):")
	dnsAcme := promptProvider("ACME DNS", existingAcme)

	fmt.Println("\nDNS provider for domain records (A/CNAME):")
	isSame := mapsEqual(existingAcme, existingRecords)
	defaultSame := "n"
	if isSame {
		defaultSame = "y"
	}
	useSame := promptChoice("Use the same provider as ACME?", []string{"y", "n"}, defaultSame)

	var dnsRecords map[string]any
	if useSame == "y" {
		dnsRecords = copyMap(dnsAcme)
	} else {
		dnsRecords = promptProvider("Records DNS", existingRecords)
	}

	fmt.Println("\nServer settings:")
	bind := prompt("Bind address", getStr(existing, "bind", "0.0.0.0"))
	portStr := prompt("Port", "8443")
	port := 8443
	if p, err := strconv.Atoi(portStr); err == nil && p > 0 {
		port = p
	}

	// Generate admin key if not present
	adminKey := getStr(existing, "admin_key", "")
	if adminKey == "" {
		adminKey = storage.GenerateToken()
	}

	config := map[string]any{
		"base_domain": baseDomain,
		"admin_key":   adminKey,
		"bind":        bind,
		"port":        port,
	}
	if mapsEqual(dnsAcme, dnsRecords) {
		config["dns"] = dnsAcme
	} else {
		config["dns_acme"] = dnsAcme
		config["dns_records"] = dnsRecords
	}

	out, _ := json.MarshalIndent(config, "", "  ")
	out = append(out, '\n')
	tmp := configPath + ".tmp"
	os.WriteFile(tmp, out, 0o644)
	os.Rename(tmp, configPath)

	// Create domains.json if missing
	domainsPath := filepath.Join(dataDir, "domains.json")
	if _, err := os.Stat(domainsPath); os.IsNotExist(err) {
		d, _ := json.MarshalIndent(map[string]any{"domains": []any{}}, "", "  ")
		d = append(d, '\n')
		tmp := domainsPath + ".tmp"
		os.WriteFile(tmp, d, 0o644)
		os.Rename(tmp, domainsPath)
	}

	fmt.Printf("\nConfig saved to %s\n", configPath)
	fmt.Printf("Admin key: %s\n\n", adminKey)
}

func mapsEqual(a, b map[string]any) bool {
	aj, _ := json.Marshal(a)
	bj, _ := json.Marshal(b)
	return string(aj) == string(bj)
}

func copyMap(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
