// ---------------------------------------------------------------------------------------
//
//	main.go (certpost)
//	------------------
//
//	CLI for the certpost client. Subcommands:
//	  fetch - Fetch certificates and save as .crt/.key files
//	  proxy - TLS termination proxy with SNI routing and auto-refresh
//	  init  - Interactive wizard to generate a config file
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
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/WaterJuice/certpost/internal/client"
	"github.com/WaterJuice/certpost/internal/colour"
	"github.com/WaterJuice/certpost/internal/proxy"
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
			fmt.Printf("certpost %s\n", version.Version)
			return 0
		}
	}

	if len(os.Args) < 2 {
		printHelp()
		return 0
	}

	switch os.Args[1] {
	case "fetch":
		return fetchCmd()
	case "proxy":
		return proxyCmd()
	case "init":
		return initCmd()
	case "sample-config":
		return sampleConfigCmd()
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
	c := colour.Prog
	h := colour.Heading
	o := colour.LongOpt
	s := colour.ShortOpt
	r := colour.Reset
	fmt.Fprintf(os.Stdout, `%scertpost%s — works with a certpost-server to manage Let's Encrypt certificates.

%squick start:%s
  1. %scertpost init%s — create a config interactively
  2. %scertpost fetch%s %s--config%s config.json — download .crt and .key files
  3. %scertpost proxy%s %s--config%s config.json — run a TLS termination proxy

%scommands:%s
  %sfetch%s           Fetch certificates and save as .crt/.key files
  %sproxy%s           TLS termination proxy with auto-refreshing certs
  %sinit%s            Generate a config file interactively
  %ssample-config%s   Print an example fetch or proxy config to stdout

%sflags:%s
  %s--version%s   Show version and exit
  %s--license%s   Show licence information and exit
  %s--help%s      Show this help
`,
		c, r,
		h, r,
		c, r,
		c, r, o, r,
		c, r, o, r,
		h, r,
		s, r,
		s, r,
		s, r,
		s, r,
		h, r,
		o, r,
		o, r,
		o, r,
	)
}

// --- Fetch ---

func fetchHelp() {
	h := colour.Heading
	o := colour.LongOpt
	s := colour.ShortOpt
	l := colour.Label
	r := colour.Reset
	fmt.Fprintf(os.Stdout, `%susage:%s certpost fetch [%s--config%s %sFILE%s] [%s--server%s %sURL%s %s--token%s %sTOKEN%s %s--domain%s %sDOMAIN%s]

Fetch certificates and save as .crt/.key files. If --domain is omitted the
domain is resolved from the token via the server. A config file with a
"domains" map ({ "domain": "token", ... }) will fetch multiple certificates
per cycle.

%soptions:%s
  %s--config%s, %s-c%s %sFILE%s        JSON config file
  %s--server%s, %s-s%s %sURL%s         certpost server URL
  %s--token%s, %s-t%s %sTOKEN%s        API token for the domain
  %s--domain%s, %s-d%s %sDOMAIN%s      Domain to fetch certificate for
  %s--output-dir%s, %s-o%s %sDIR%s     Directory to save certificate files (default: .)
  %s--refresh%s %sHOURS%s          Re-fetch interval in hours (default: 0)
`,
		h, r, o, r, l, r, o, r, l, r, o, r, l, r, o, r, l, r,
		h, r,
		o, r, s, r, l, r,
		o, r, s, r, l, r,
		o, r, s, r, l, r,
		o, r, s, r, l, r,
		o, r, s, r, l, r,
		o, r, l, r,
	)
}

func fetchCmd() int {
	fs := flag.NewFlagSet("fetch", flag.ContinueOnError)
	fs.Usage = fetchHelp
	serverURL := fs.String("s", "", "")
	fs.StringVar(serverURL, "server", "", "")
	token := fs.String("t", "", "")
	fs.StringVar(token, "token", "", "")
	domain := fs.String("d", "", "")
	fs.StringVar(domain, "domain", "", "")
	outputDir := fs.String("o", ".", "")
	fs.StringVar(outputDir, "output-dir", ".", "")
	refresh := fs.Int("refresh", 0, "")
	configFile := fs.String("c", "", "")
	fs.StringVar(configFile, "config", "", "")

	if err := fs.Parse(os.Args[2:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 1
	}

	type domainToken struct{ domain, token string }
	var domains []domainToken

	if *configFile != "" {
		config, err := loadConfig(*configFile)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			return 1
		}
		if s, ok := config["server"].(string); ok && *serverURL == "" {
			*serverURL = s
		}
		if t, ok := config["token"].(string); ok && *token == "" {
			*token = t
		}
		if d, ok := config["domain"].(string); ok && *domain == "" {
			*domain = d
		}
		if o, ok := config["output_dir"].(string); ok && *outputDir == "." {
			*outputDir = o
		}
		if h, ok := config["refresh_hours"].(float64); ok && *refresh == 0 {
			*refresh = int(h)
		}
		if m, ok := config["domains"].(map[string]any); ok {
			if _, flat := config["domain"]; flat {
				fmt.Fprintln(os.Stderr, "Warning: config has both \"domains\" map and top-level \"domain\"/\"token\" — using \"domains\"")
			}
			for d, tRaw := range m {
				t, ok := tRaw.(string)
				if !ok || t == "" {
					fmt.Fprintf(os.Stderr, "Error: domains[%q] must be a non-empty token string\n", d)
					return 1
				}
				domains = append(domains, domainToken{d, t})
			}
		}
	}

	if len(domains) == 0 {
		if *serverURL == "" || *token == "" {
			fmt.Fprintln(os.Stderr, "Error: --server and --token are required (or use --config with \"domain\"/\"token\" or \"domains\")")
			return 1
		}
		resolved := client.ResolveTokenDomain(*serverURL, *token)
		if *domain == "" {
			if resolved == "" {
				fmt.Fprintln(os.Stderr, "Error: could not resolve domain from token — pass --domain explicitly")
				return 1
			}
			*domain = resolved
		} else if resolved != "" && resolved != *domain {
			fmt.Fprintf(os.Stderr, "Error: --domain %q does not match token's domain %q\n", *domain, resolved)
			return 1
		}
		domains = append(domains, domainToken{*domain, *token})
	} else if *serverURL == "" {
		fmt.Fprintln(os.Stderr, "Error: --server is required (or set \"server\" in config)")
		return 1
	}

	refreshSeconds := *refresh * 3600

	for {
		anyFailed := false
		for _, dt := range domains {
			fmt.Fprintf(os.Stderr, "Fetching certificate for %s...\n", dt.domain)
			data, err := client.FetchCert(*serverURL, dt.token, dt.domain)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				anyFailed = true
				continue
			}
			if err := client.SaveCert(*outputDir, dt.domain, data); err != nil {
				fmt.Fprintf(os.Stderr, "Error saving cert: %v\n", err)
				anyFailed = true
			}
		}

		if refreshSeconds <= 0 {
			if anyFailed {
				return 1
			}
			break
		}

		fmt.Fprintf(os.Stderr, "Next refresh in %dh\n", *refresh)
		time.Sleep(time.Duration(refreshSeconds) * time.Second)
	}
	return 0
}

// --- Proxy ---

func proxyHelp() {
	h := colour.Heading
	o := colour.LongOpt
	s := colour.ShortOpt
	l := colour.Label
	r := colour.Reset
	fmt.Fprintf(os.Stdout, `%susage:%s certpost proxy [%s--listen%s %sADDR%s] %s--config%s %sFILE%s

TLS termination proxy with SNI routing and auto-refreshing certs

%soptions:%s
  %s--listen%s %sADDR%s             Listen address (default: 0.0.0.0:443)
  %s--config%s, %s-c%s %sFILE%s        JSON config file
`,
		h, r, o, r, l, r, o, r, l, r,
		h, r,
		o, r, l, r,
		o, r, s, r, l, r,
	)
}

func proxyCmd() int {
	fs := flag.NewFlagSet("proxy", flag.ContinueOnError)
	fs.Usage = proxyHelp
	configFile := fs.String("c", "", "")
	fs.StringVar(configFile, "config", "", "")
	listen := fs.String("listen", "0.0.0.0:443", "")

	if err := fs.Parse(os.Args[2:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 1
	}

	if *configFile == "" {
		fmt.Fprintln(os.Stderr, "Error: --config is required for proxy mode")
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "Use 'certpost init' to create a config file.")
		return 1
	}

	data, err := os.ReadFile(*configFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}

	var cfg proxy.Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing config: %v\n", err)
		return 1
	}

	if *listen != "0.0.0.0:443" {
		cfg.Listen = *listen
	} else if cfg.Listen == "" {
		cfg.Listen = "0.0.0.0:443"
	}

	if err := proxy.Run(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}
	return 0
}

// --- Init ---

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

func initHelp() {
	h := colour.Heading
	o := colour.LongOpt
	s := colour.ShortOpt
	l := colour.Label
	r := colour.Reset
	fmt.Fprintf(os.Stdout, `%susage:%s certpost init [%s--output%s %sFILE%s]

Generate a fetch or proxy config file interactively

%soptions:%s
  %s--output%s, %s-o%s %sFILE%s   Output config file path (default: certpost.json)
`,
		h, r, o, r, l, r,
		h, r,
		o, r, s, r, l, r,
	)
}

func initCmd() int {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	fs.Usage = initHelp
	output := fs.String("o", "certpost.json", "")
	fs.StringVar(output, "output", "certpost.json", "")

	if err := fs.Parse(os.Args[2:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 1
	}

	if _, err := os.Stat(*output); err == nil {
		fmt.Printf("%s already exists. Overwrite? [y/N]: ", *output)
		scanner.Scan()
		if strings.TrimSpace(strings.ToLower(scanner.Text())) != "y" {
			fmt.Fprintln(os.Stderr, "Aborted.")
			return 1
		}
	}

	fmt.Println("\ncertpost config generator")
	fmt.Println("Press Enter to skip any field — you can fill it in later.")
	fmt.Println()

	fmt.Println("What do you need?")
	fmt.Println("  1. fetch  — download cert files to disk (one-shot or scheduled)")
	fmt.Println("  2. proxy  — TLS termination proxy (auto-fetches and refreshes certs)")
	mode := prompt("Choose [1/2]", "2")

	serverURL := prompt("certpost server URL (e.g. http://certpost.example.com:8443)", "")

	var config map[string]any
	if mode == "2" {
		config = buildProxyConfig(serverURL)
	} else {
		config = buildFetchConfig(serverURL)
	}

	// Validate against server
	if serverURL != "" {
		fmt.Println("\nValidating configuration against server...")
		validateConfig(serverURL, config, mode)
	}

	out, _ := json.MarshalIndent(config, "", "  ")
	out = append(out, '\n')
	tmp := *output + ".tmp"
	os.WriteFile(tmp, out, 0o644)
	os.Rename(tmp, *output)

	fmt.Printf("\nConfig saved to %s\n", *output)
	if mode == "2" {
		fmt.Printf("Run with: certpost proxy -c %s\n\n", *output)
	} else {
		fmt.Printf("Run with: certpost fetch -c %s\n\n", *output)
	}
	return 0
}

// promptTokenDomain prompts for an API token and resolves (or asks for) its
// domain. Returns ("", "") when the user enters an empty token to end input.
func promptTokenDomain(serverURL string) (domain, token string) {
	for {
		token = prompt("API token (from certpost admin panel)", "")
		if token == "" {
			return "", ""
		}
		domain = client.ResolveTokenDomain(serverURL, token)
		if domain != "" {
			fmt.Printf("  Domain: %s\n", domain)
			return domain, token
		}
		domain = prompt("  Could not look up domain. Enter it manually", "")
		if domain != "" {
			return domain, token
		}
	}
}

func buildFetchConfig(serverURL string) map[string]any {
	fmt.Println("\nFetch settings:")
	outputDir := prompt("Output directory for cert files", ".")
	refreshStr := prompt("Refresh interval in hours (0 = once)", "0")
	refreshHours := 0
	if n, err := strconv.Atoi(refreshStr); err == nil && n > 0 {
		refreshHours = n
	}

	fmt.Println("\nAdd domains. Enter empty token when done.")
	fmt.Println()
	domains := map[string]any{}
	for {
		domain, token := promptTokenDomain(serverURL)
		if token == "" {
			break
		}
		domains[domain] = token
		fmt.Println()
	}

	cfg := map[string]any{
		"server":        serverURL,
		"output_dir":    outputDir,
		"refresh_hours": refreshHours,
	}

	// Single domain: keep legacy flat form so older clients still read it.
	if len(domains) == 1 {
		for d, t := range domains {
			cfg["domain"] = d
			cfg["token"] = t
		}
	} else {
		cfg["domains"] = domains
	}
	return cfg
}

func buildProxyConfig(serverURL string) map[string]any {
	fmt.Println("\nProxy settings:")
	listenInput := prompt("Listen port or address", "443")
	listen := listenInput
	if isAllDigits(listenInput) {
		listen = "0.0.0.0:" + listenInput
	}
	refreshStr := prompt("Certificate refresh interval in hours", "24")
	refreshHours := 24
	if n, err := strconv.Atoi(refreshStr); err == nil && n > 0 {
		refreshHours = n
	}

	routes := map[string]any{}
	fmt.Println("\nAdd routes. Enter empty token when done.")
	fmt.Println()
	for {
		domain, token := promptTokenDomain(serverURL)
		if token == "" {
			break
		}
		backend := ""
		for backend == "" {
			backend = prompt(fmt.Sprintf("  Backend address for %s (e.g. 127.0.0.1:8080)", domain), "")
			if backend == "" {
				fmt.Println("  Backend address is required.")
			}
		}
		routes[domain] = map[string]any{"token": token, "backend": backend}
		fmt.Println()
	}

	return map[string]any{
		"server":        serverURL,
		"listen":        listen,
		"refresh_hours": refreshHours,
		"routes":        routes,
	}
}

func validateConfig(serverURL string, config map[string]any, mode string) {
	url := strings.TrimRight(serverURL, "/") + "/api/version"
	resp, err := http.Get(url)
	if err != nil {
		fmt.Printf("  WARNING: Could not reach server: %v\n", err)
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var versionData map[string]string
	json.Unmarshal(body, &versionData)
	fmt.Printf("  Server: %s %s\n", versionData["product"], versionData["server_version"])

	if mode == "2" {
		routes, _ := config["routes"].(map[string]any)
		for domain, routeRaw := range routes {
			route, _ := routeRaw.(map[string]any)
			token, _ := route["token"].(string)
			reportValidate(serverURL, token, domain)
		}
	} else if domains, ok := config["domains"].(map[string]any); ok {
		for domain, tRaw := range domains {
			token, _ := tRaw.(string)
			reportValidate(serverURL, token, domain)
		}
	} else {
		domain, _ := config["domain"].(string)
		token, _ := config["token"].(string)
		if domain != "" && token != "" {
			reportValidate(serverURL, token, domain)
		}
	}
}

func reportValidate(serverURL, token, domain string) {
	if validateToken(serverURL, token, domain) {
		fmt.Printf("  %s: OK\n", domain)
	} else {
		fmt.Printf("  %s: WARNING — token could not fetch cert (domain may not be issued yet)\n", domain)
	}
}

func validateToken(serverURL, token, domain string) bool {
	if serverURL == "" || token == "" || domain == "" {
		return false
	}
	_, err := client.FetchCert(serverURL, token, domain)
	return err == nil
}

const sampleFetchSingle = `{
  "server": "http://certpost.example.com:8443",
  "domain": "app.example.com",
  "token": "your-api-token",
  "output_dir": "/etc/ssl/certs",
  "refresh_hours": 24
}
`

const sampleFetchMulti = `{
  "server": "http://certpost.example.com:8443",
  "output_dir": "/etc/ssl/certs",
  "refresh_hours": 24,
  "domains": {
    "app.example.com": "token-for-app",
    "api.example.com": "token-for-api"
  }
}
`

const sampleProxy = `{
  "server": "http://certpost.example.com:8443",
  "listen": "0.0.0.0:443",
  "refresh_hours": 24,
  "routes": {
    "app.example.com": {
      "token": "token-for-app",
      "backend": "127.0.0.1:8080"
    },
    "api.example.com": {
      "token": "token-for-api",
      "backend": "127.0.0.1:9090"
    }
  }
}
`

func sampleConfigHelp() {
	h := colour.Heading
	o := colour.LongOpt
	l := colour.Label
	r := colour.Reset
	fmt.Fprintf(os.Stdout, `%susage:%s certpost sample-config %sKIND%s [%s--output%s %sFILE%s]

Print an example config file to stdout (or write to a file). When --output is
used, certpost refuses to overwrite an existing file.

%skinds:%s
  fetch         Single-domain fetch config
  fetch-multi   Multi-domain fetch config (uses "domains" map)
  proxy         TLS termination proxy config

%soptions:%s
  %s--output%s, -o %sFILE%s   Write to FILE instead of stdout
`,
		h, r, l, r, o, r, l, r,
		h, r,
		h, r,
		o, r, l, r,
	)
}

func sampleConfigCmd() int {
	fs := flag.NewFlagSet("sample-config", flag.ContinueOnError)
	fs.Usage = sampleConfigHelp
	output := fs.String("o", "", "")
	fs.StringVar(output, "output", "", "")

	if err := fs.Parse(os.Args[2:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 1
	}

	args := fs.Args()
	if len(args) != 1 {
		sampleConfigHelp()
		return 1
	}

	var sample string
	switch args[0] {
	case "fetch":
		sample = sampleFetchSingle
	case "fetch-multi":
		sample = sampleFetchMulti
	case "proxy":
		sample = sampleProxy
	default:
		fmt.Fprintf(os.Stderr, "Unknown kind: %s (expected fetch, fetch-multi, or proxy)\n", args[0])
		return 1
	}

	if *output == "" {
		fmt.Print(sample)
		return 0
	}

	if _, err := os.Stat(*output); err == nil {
		fmt.Fprintf(os.Stderr, "Error: %s already exists\n", *output)
		return 1
	}
	if err := os.WriteFile(*output, []byte(sample), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return 1
	}
	fmt.Fprintf(os.Stderr, "Wrote sample %s config to %s\n", args[0], *output)
	return 0
}

func loadConfig(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("config file not found: %s", path)
	}
	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("invalid JSON in %s: %w", path, err)
	}
	return result, nil
}

func isAllDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
