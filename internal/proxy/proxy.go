// ---------------------------------------------------------------------------------------
//
//	proxy.go
//	--------
//
//	TLS termination proxy with SNI-based routing. Fetches certificates from a
//	certpost server, terminates TLS, and forwards plaintext to backend servers.
//	Certificates are refreshed automatically on a configurable interval.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package proxy

import (
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"time"

	"github.com/WaterJuice/certpost/internal/client"
)

const bufferSize = 65536

// Route represents a proxy route configuration.
type Route struct {
	Token   string `json:"token"`
	Backend string `json:"backend"`
}

// Config holds the proxy configuration.
type Config struct {
	Server       string           `json:"server"`
	Listen       string           `json:"listen"`
	RefreshHours int              `json:"refresh_hours"`
	Routes       map[string]Route `json:"routes"`
}

// --- Certificate Store ---

type certStore struct {
	mu    sync.RWMutex
	certs map[string]*tls.Certificate
}

func newCertStore() *certStore {
	return &certStore{certs: make(map[string]*tls.Certificate)}
}

func (cs *certStore) update(domain string, data *client.CertData) error {
	fullChain := data.CertPEM + data.ChainPEM
	cert, err := tls.X509KeyPair([]byte(fullChain), []byte(data.KeyPEM))
	if err != nil {
		return fmt.Errorf("load cert for %s: %w", domain, err)
	}

	cs.mu.Lock()
	cs.certs[domain] = &cert
	cs.mu.Unlock()

	fmt.Fprintf(os.Stderr, "  [proxy] Certificate loaded for %s\n", domain)
	return nil
}

func (cs *certStore) get(domain string) *tls.Certificate {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	return cs.certs[domain]
}

func (cs *certStore) has(domain string) bool {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	_, ok := cs.certs[domain]
	return ok
}

func (cs *certStore) anyDomain() *tls.Certificate {
	cs.mu.RLock()
	defer cs.mu.RUnlock()
	for _, cert := range cs.certs {
		return cert
	}
	return nil
}

// --- Cert Refresher ---

func fetchAll(store *certStore, serverURL string, routes map[string]Route) {
	for domain, route := range routes {
		data, err := client.FetchCert(serverURL, route.Token, domain)
		if err != nil {
			fmt.Fprintf(os.Stderr, "  [proxy] Failed to fetch cert for %s: %v\n", domain, err)
			continue
		}
		if err := store.update(domain, data); err != nil {
			fmt.Fprintf(os.Stderr, "  [proxy] Failed to load cert for %s: %v\n", domain, err)
		}
	}
}

func startRefresher(store *certStore, serverURL string, routes map[string]Route, intervalHours int) {
	interval := time.Duration(intervalHours) * time.Hour
	go func() {
		for {
			time.Sleep(interval)
			fmt.Fprintf(os.Stderr, "  [proxy] Refreshing certificates...\n")
			fetchAll(store, serverURL, routes)
		}
	}()
}

// --- Proxy ---

func forward(clientConn net.Conn, backendAddr string) {
	defer clientConn.Close()

	backendConn, err := net.DialTimeout("tcp", backendAddr, 10*time.Second)
	if err != nil {
		fmt.Fprintf(os.Stderr, "  [proxy] Backend connection failed (%s): %v\n", backendAddr, err)
		return
	}
	defer backendConn.Close()

	var wg sync.WaitGroup
	wg.Add(2)

	pipe := func(dst, src net.Conn) {
		defer wg.Done()
		io.Copy(dst, src)
		if cw, ok := dst.(interface{ CloseWrite() error }); ok {
			cw.CloseWrite()
		}
	}

	go pipe(backendConn, clientConn)
	go pipe(clientConn, backendConn)
	wg.Wait()
}

// Run starts the TLS termination proxy.
func Run(cfg Config) error {
	if cfg.Server == "" {
		return fmt.Errorf("'server' is required in config")
	}
	if len(cfg.Routes) == 0 {
		return fmt.Errorf("'routes' is required in config")
	}
	if cfg.RefreshHours <= 0 {
		cfg.RefreshHours = 24
	}

	// Parse listen address
	listenAddr := cfg.Listen
	if listenAddr == "" {
		listenAddr = "0.0.0.0:443"
	}
	host, port, err := net.SplitHostPort(listenAddr)
	if err != nil {
		// Might be just a port number
		host = "0.0.0.0"
		port = listenAddr
		listenAddr = host + ":" + port
	}
	_ = host

	// Build backend map
	backendMap := make(map[string]string)
	for domain, route := range cfg.Routes {
		if route.Backend == "" {
			return fmt.Errorf("'backend' is required for route '%s'", domain)
		}
		backendMap[domain] = route.Backend
	}

	// Initialise cert store and fetch initial certs
	store := newCertStore()
	fmt.Fprintf(os.Stderr, "  [proxy] Fetching initial certificates...\n")
	fetchAll(store, cfg.Server, cfg.Routes)

	// Check at least one cert loaded
	var loaded []string
	for domain := range cfg.Routes {
		if store.has(domain) {
			loaded = append(loaded, domain)
		}
	}
	if len(loaded) == 0 {
		return fmt.Errorf("no certificates could be loaded")
	}

	// Start background refresh
	startRefresher(store, cfg.Server, cfg.Routes, cfg.RefreshHours)

	// TLS config with SNI-based cert selection
	tlsConfig := &tls.Config{
		MinVersion: tls.VersionTLS12,
		GetCertificate: func(info *tls.ClientHelloInfo) (*tls.Certificate, error) {
			if cert := store.get(info.ServerName); cert != nil {
				return cert, nil
			}
			// Fall back to any available cert
			if cert := store.anyDomain(); cert != nil {
				return cert, nil
			}
			return nil, fmt.Errorf("no certificate available")
		},
	}

	// Start listening
	listener, err := tls.Listen("tcp", listenAddr, tlsConfig)
	if err != nil {
		return fmt.Errorf("could not bind to %s: %w", listenAddr, err)
	}
	defer listener.Close()

	fmt.Fprintf(os.Stderr, "  [proxy] Listening on %s\n", listenAddr)
	for domain, backend := range backendMap {
		status := "ready"
		if !store.has(domain) {
			status = "no cert"
		}
		fmt.Fprintf(os.Stderr, "  [proxy]   %s -> %s [%s]\n", domain, backend, status)
	}
	fmt.Fprintf(os.Stderr, "  [proxy] Certificates refresh every %dh\n", cfg.RefreshHours)

	for {
		conn, err := listener.Accept()
		if err != nil {
			fmt.Fprintf(os.Stderr, "  [proxy] Accept error: %v\n", err)
			continue
		}

		// Get SNI from TLS connection
		tlsConn, ok := conn.(*tls.Conn)
		if !ok {
			conn.Close()
			continue
		}

		go func() {
			// The TLS handshake happens during Accept for tls.Listener,
			// but we need to access the server name from ConnectionState.
			if err := tlsConn.Handshake(); err != nil {
				fmt.Fprintf(os.Stderr, "  [proxy] TLS handshake failed: %v\n", err)
				tlsConn.Close()
				return
			}

			serverName := tlsConn.ConnectionState().ServerName
			backend, ok := backendMap[serverName]
			if !ok {
				fmt.Fprintf(os.Stderr, "  [proxy] No route for %s\n", serverName)
				tlsConn.Close()
				return
			}

			forward(tlsConn, backend)
		}()
	}
}
