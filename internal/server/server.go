// ---------------------------------------------------------------------------------------
//
//	server.go
//	---------
//
//	HTTP server for certpost. Serves the admin panel (protected by login key),
//	handles API requests for certificate retrieval (per-domain bearer token),
//	and manages subdomains.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"

	"github.com/WaterJuice/certpost/internal/acme"
	"github.com/WaterJuice/certpost/internal/dns"
	"github.com/WaterJuice/certpost/internal/logbuf"
	"github.com/WaterJuice/certpost/internal/oidcauth"
	"github.com/WaterJuice/certpost/internal/renewal"
	"github.com/WaterJuice/certpost/internal/storage"
	"github.com/WaterJuice/certpost/internal/version"
	"github.com/WaterJuice/certpost/internal/web"
)

const (
	// sessionCookie is the admin-key session cookie; its value is a SHA-256
	// hash of the admin key.
	sessionCookie = "certpost_session"
	// oidcCookie is the OIDC session cookie; its value is an opaque session id
	// resolved via oidcauth (distinct from the admin-key cookie).
	oidcCookie = "certpost_oidc"
)

// Server holds all server state.
type Server struct {
	storage         *storage.Storage
	acmeClient      *acme.Client
	dnsRecords      dns.Provider
	cancelFunc      context.CancelFunc
	adminKeyEnabled bool           // whether an admin-key login is configured
	oidc            *oidcauth.Auth // OIDC login, or nil when not configured
	oidcLabel       string         // provider name on the login button
}

// Run starts the certpost HTTP server.
func Run(host string, port int, dataDir string) error {
	return RunWithOptions(host, port, dataDir, false)
}

// RunWithOptions starts the server with additional options. When demo is
// true, DNS providers are replaced with no-op stubs and the renewal/ACME
// network work is skipped — the admin panel and APIs still function for
// local preview, but no external services are contacted.
func RunWithOptions(host string, port int, dataDir string, demo bool) error {
	s, err := storage.New(dataDir)
	if err != nil {
		return fmt.Errorf("initialise storage: %w", err)
	}

	config, err := s.GetConfig()
	if err != nil {
		return fmt.Errorf("read config: %w", err)
	}

	adminKey, _ := config["admin_key"].(string)

	// Authentication is either an admin key or OIDC — never both. config.json
	// may carry an "oidc" block as an alternative to "admin_key".
	oidcAuth, oidcLabel, err := buildOIDC(config, adminKey)
	if err != nil {
		return fmt.Errorf("oidc config: %w", err)
	}

	if oidcAuth != nil {
		fmt.Fprintf(os.Stderr, "  Auth: OIDC (%s)\n", oidcLabel)
	} else if adminKey != "" {
		fmt.Fprintf(os.Stderr, "  Admin key: %s\n", adminKey)
	} else {
		fmt.Fprintln(os.Stderr, "  Auth: none — admin panel is open")
	}
	if demo {
		fmt.Fprintln(os.Stderr, "  Demo mode: DNS calls and ACME renewal are disabled")
	}

	dnsAcmeConfig := map[string]any{"provider": "demo"}
	dnsRecordsConfig := map[string]any{"provider": "demo"}
	if !demo {
		dnsShared, _ := config["dns"].(map[string]any)
		if dnsShared == nil {
			dnsShared = map[string]any{}
		}
		if c, _ := config["dns_acme"].(map[string]any); c != nil {
			dnsAcmeConfig = c
		} else {
			dnsAcmeConfig = dnsShared
		}
		if c, _ := config["dns_records"].(map[string]any); c != nil {
			dnsRecordsConfig = c
		} else {
			dnsRecordsConfig = dnsShared
		}
	}

	dnsAcme, err := dns.CreateProvider(dnsAcmeConfig)
	if err != nil {
		return fmt.Errorf("create ACME DNS provider: %w", err)
	}
	dnsRecords, err := dns.CreateProvider(dnsRecordsConfig)
	if err != nil {
		return fmt.Errorf("create records DNS provider: %w", err)
	}

	acmeProviderName, _ := dnsAcmeConfig["provider"].(string)
	recordsProviderName, _ := dnsRecordsConfig["provider"].(string)
	fmt.Fprintf(os.Stderr, "  DNS (ACME): %s\n", acmeProviderName)
	fmt.Fprintf(os.Stderr, "  DNS (records): %s\n", recordsProviderName)

	acmeClient := acme.NewClient(s, dnsAcme)
	ctx, cancel := context.WithCancel(context.Background())

	if !demo {
		if err := acmeClient.Initialise(); err != nil {
			logbuf.Log("server", fmt.Sprintf("Warning: ACME initialisation failed: %v", err))
			logbuf.Log("server", "Certificate operations will not work until config is corrected.")
		}
		renewal.Start(ctx, s, acmeClient)
	} else {
		logbuf.Log("server", "Demo mode active — ACME, DNS and renewal are no-ops")
	}

	srv := &Server{
		storage:         s,
		acmeClient:      acmeClient,
		dnsRecords:      dnsRecords,
		cancelFunc:      cancel,
		adminKeyEnabled: adminKey != "",
		oidc:            oidcAuth,
		oidcLabel:       oidcLabel,
	}

	mux := http.NewServeMux()

	// Public routes
	mux.HandleFunc("GET /", srv.handleAdminPanel)
	mux.HandleFunc("GET /index.html", srv.handleAdminPanel)
	mux.HandleFunc("GET /api/version", srv.handleGetVersion)
	mux.HandleFunc("GET /api/spec", srv.handleGetSpec)
	mux.HandleFunc("GET /api/help", srv.handleGetHelp)
	mux.HandleFunc("GET /api/token-info", srv.handleTokenInfo)
	mux.HandleFunc("GET /api/cert/{domain...}", srv.handleGetCert)
	mux.HandleFunc("GET /api/auth/check", srv.handleAuthCheck)

	// Admin routes
	mux.HandleFunc("POST /api/auth/login", srv.handleLogin)
	mux.HandleFunc("POST /api/auth/logout", srv.handleLogout)

	// OIDC routes (registered only when OIDC login is configured)
	if oidcAuth != nil {
		mux.HandleFunc("GET /oauth/login", srv.handleOIDCLogin)
		// The callback is served at the redirect URL's path so it byte-matches
		// the value registered with the provider.
		logbuf.Log("server", fmt.Sprintf("OIDC callback registered at %s", oidcAuth.CallbackPath()))
		mux.HandleFunc("GET "+oidcAuth.CallbackPath(), srv.handleOIDCCallback)
	}
	mux.HandleFunc("GET /api/domains", srv.requireAdmin(srv.handleGetDomains))
	mux.HandleFunc("GET /api/base-domain", srv.requireAdmin(srv.handleGetBaseDomain))
	mux.HandleFunc("GET /api/logs", srv.requireAdmin(srv.handleGetLogs))
	mux.HandleFunc("GET /api/prefs", srv.requireAdmin(srv.handleGetPrefs))
	mux.HandleFunc("POST /api/prefs", srv.requireAdmin(srv.handleSavePrefs))
	mux.HandleFunc("POST /api/domains", srv.requireAdmin(srv.handleAddDomain))
	mux.HandleFunc("POST /api/domains/{sub...}", srv.handleDomainPost)
	mux.HandleFunc("DELETE /api/domains/{sub...}", srv.requireAdmin(srv.handleRemoveDomain))

	addr := fmt.Sprintf("%s:%d", host, port)
	httpServer := &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	defer func() {
		cancel()
		httpServer.Close()
	}()

	return httpServer.ListenAndServe()
}

// --- Middleware ---

func (s *Server) requireAdmin(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.isAdminAuthenticated(r) {
			sendError(w, 401, "Not authenticated")
			return
		}
		next(w, r)
	}
}

// isAdminAuthenticated reports whether r carries a valid admin session. When no
// login is configured (neither admin key nor OIDC) the panel is open and every
// request is treated as authenticated; otherwise either a valid admin-key
// cookie or a valid OIDC session is accepted.
func (s *Server) isAdminAuthenticated(r *http.Request) bool {
	if !s.adminKeyEnabled && s.oidc == nil {
		return true
	}
	if s.adminKeyEnabled {
		if cookie, err := r.Cookie(sessionCookie); err == nil && s.storage.VerifyAdminCookie(cookie.Value) {
			return true
		}
	}
	_, ok := s.oidcSession(r)
	return ok
}

// oidcSession resolves the OIDC session carried by r, if any.
func (s *Server) oidcSession(r *http.Request) (oidcauth.Session, bool) {
	if s.oidc == nil {
		return oidcauth.Session{}, false
	}
	cookie, err := r.Cookie(oidcCookie)
	if err != nil {
		return oidcauth.Session{}, false
	}
	return s.oidc.SessionFor(cookie.Value)
}

// --- Admin panel ---

func (s *Server) handleAdminPanel(w http.ResponseWriter, r *http.Request) {
	// Only serve admin panel for root path
	if r.URL.Path != "/" && r.URL.Path != "/index.html" {
		sendError(w, 404, "Not found")
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Write(web.AdminHTML)
}

// --- Auth handlers ---

func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	if !s.adminKeyEnabled {
		sendError(w, 400, "Admin key login is not enabled")
		return
	}

	body, err := readBody(r)
	if err != nil {
		sendError(w, 400, "Invalid JSON")
		return
	}

	key, _ := body["key"].(string)
	if !s.storage.VerifyAdminKey(key) {
		sendError(w, 403, "Invalid admin key")
		return
	}

	remember, _ := body["remember"].(bool)
	maxAge := 0 // session cookie unless "remember me" is ticked
	if remember {
		maxAge = 2592000
	}
	setSessionCookie(w, sessionCookie, s.storage.AdminCookieValue(), maxAge, http.SameSiteStrictMode, false)
	sendJSON(w, 200, map[string]string{"status": "ok"})
}

// handleLogout clears both possible session cookies and, for OIDC, forgets the
// server-side session. Clearing an unset cookie is a harmless no-op.
func (s *Server) handleLogout(w http.ResponseWriter, r *http.Request) {
	if s.oidc != nil {
		if cookie, err := r.Cookie(oidcCookie); err == nil {
			s.oidc.EndSession(cookie.Value)
		}
	}
	setSessionCookie(w, sessionCookie, "", -1, http.SameSiteStrictMode, false)
	setSessionCookie(w, oidcCookie, "", -1, http.SameSiteLaxMode, false)
	sendJSON(w, 200, map[string]string{"status": "ok"})
}

func (s *Server) handleAuthCheck(w http.ResponseWriter, r *http.Request) {
	username := ""
	if sess, ok := s.oidcSession(r); ok {
		username = sess.Username
	}
	sendJSON(w, 200, map[string]any{
		"authenticated":     s.isAdminAuthenticated(r),
		"admin_key_enabled": s.adminKeyEnabled,
		"oidc_enabled":      s.oidc != nil,
		"oidc_label":        s.oidcLabel,
		"username":          username,
	})
}

// handleOIDCLogin starts the OIDC flow by redirecting the browser to the
// provider's authorise endpoint.
func (s *Server) handleOIDCLogin(w http.ResponseWriter, r *http.Request) {
	if s.oidc == nil {
		http.NotFound(w, r)
		return
	}
	loginURL, err := s.oidc.LoginURL(r.Context())
	if err != nil {
		logbuf.Log("server", fmt.Sprintf("OIDC login URL failed: %v", err))
		http.Redirect(w, r, "/?oidc_error="+url.QueryEscape("Login is temporarily unavailable. Please try again."), http.StatusSeeOther)
		return
	}
	http.Redirect(w, r, loginURL, http.StatusSeeOther)
}

// handleOIDCCallback completes the OIDC flow: it validates the callback,
// establishes a session, sets the session cookie, and redirects back to the
// admin panel. Failures redirect to the panel with an ?oidc_error message.
func (s *Server) handleOIDCCallback(w http.ResponseWriter, r *http.Request) {
	if s.oidc == nil {
		http.NotFound(w, r)
		return
	}
	q := r.URL.Query()
	sess, err := s.oidc.Complete(r.Context(), q.Get("code"), q.Get("state"))
	if err != nil {
		logbuf.Log("server", fmt.Sprintf("OIDC login rejected: %v", err))
		http.Redirect(w, r, "/?oidc_error="+url.QueryEscape(oidcErrorMessage(err)), http.StatusSeeOther)
		return
	}
	sid := s.oidc.StartSession(sess)
	const oneYear = 365 * 24 * 60 * 60
	setSessionCookie(w, oidcCookie, sid, oneYear, http.SameSiteLaxMode, s.oidc.RedirectIsHTTPS())
	logbuf.Log("server", fmt.Sprintf("OIDC login: %s", sess.Username))
	http.Redirect(w, r, "/", http.StatusSeeOther)
}

// oidcErrorMessage maps an oidcauth.Complete failure to a user-facing message,
// distinguishing a genuine authorisation denial from an expired round-trip or
// a provider being unreachable.
func oidcErrorMessage(cause error) string {
	switch {
	case errors.Is(cause, oidcauth.ErrForbidden):
		return "Your account is not permitted to access this panel."
	case errors.Is(cause, oidcauth.ErrInvalidState):
		return "Your login session expired. Please try again."
	default:
		return "Login failed. Please try again."
	}
}

// buildOIDC parses and validates the optional "oidc" block from config. It
// returns nil when no OIDC block is present. An OIDC block and a non-empty
// admin key are mutually exclusive.
func buildOIDC(config map[string]any, adminKey string) (*oidcauth.Auth, string, error) {
	raw, ok := config["oidc"].(map[string]any)
	if !ok || raw == nil {
		return nil, "", nil
	}
	if adminKey != "" {
		return nil, "", errors.New("admin_key and oidc are mutually exclusive")
	}

	issuer, _ := raw["issuer"].(string)
	clientID, _ := raw["client_id"].(string)
	clientSecret, _ := raw["client_secret"].(string)
	redirectURL, _ := raw["redirect_url"].(string)
	label, _ := raw["label"].(string)

	var users []string
	if arr, ok := raw["authorised_users"].([]any); ok {
		for _, u := range arr {
			if str, ok := u.(string); ok && str != "" {
				users = append(users, str)
			}
		}
	}

	switch {
	case issuer == "":
		return nil, "", errors.New("oidc.issuer is required")
	case clientID == "":
		return nil, "", errors.New("oidc.client_id is required")
	case clientSecret == "":
		return nil, "", errors.New("oidc.client_secret is required")
	case redirectURL == "":
		return nil, "", errors.New("oidc.redirect_url is required")
	case len(users) == 0:
		return nil, "", errors.New("oidc.authorised_users must list at least one user")
	}

	// The callback is served at the redirect URL's path, so it must be a
	// dedicated path (e.g. /auth-callback). An empty or root path would collide
	// with the admin panel's own routes and panic the router.
	if u, err := url.Parse(redirectURL); err != nil {
		return nil, "", fmt.Errorf("oidc.redirect_url is not a valid URL: %w", err)
	} else if u.Path == "" || u.Path == "/" {
		return nil, "", errors.New("oidc.redirect_url must include a dedicated path, e.g. /auth-callback")
	}

	if label = strings.TrimSpace(label); label == "" {
		label = "SSO"
	}

	auth := oidcauth.New(oidcauth.Config{
		Issuer:          issuer,
		ClientID:        clientID,
		ClientSecret:    clientSecret,
		RedirectURI:     redirectURL,
		AuthorisedUsers: users,
	})
	return auth, label, nil
}

// --- Domain handlers ---

func (s *Server) handleGetDomains(w http.ResponseWriter, r *http.Request) {
	domains, err := s.storage.GetDomains()
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, map[string]any{"domains": domains})
}

func (s *Server) handleGetBaseDomain(w http.ResponseWriter, r *http.Request) {
	config, err := s.storage.GetConfig()
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	baseDomain, _ := config["base_domain"].(string)
	sendJSON(w, 200, map[string]string{"base_domain": baseDomain})
}

func (s *Server) handleGetPrefs(w http.ResponseWriter, r *http.Request) {
	prefs, err := s.storage.GetPrefs()
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, prefs)
}

// allowedPrefKeys lists every key the admin panel is permitted to persist
// in prefs.json. Unknown keys are rejected so typos or future client bugs
// can't silently accumulate stale entries on disk.
var allowedPrefKeys = map[string]bool{
	"export_format": true,
	"export_server": true,
	"sort_by":       true,
	"sort_dir":      true,
}

func (s *Server) handleSavePrefs(w http.ResponseWriter, r *http.Request) {
	body, err := readBody(r)
	if err != nil {
		sendError(w, 400, "Invalid JSON")
		return
	}
	for k := range body {
		if !allowedPrefKeys[k] {
			sendError(w, 400, fmt.Sprintf("unknown preference key: %q", k))
			return
		}
	}
	if err := s.storage.SavePrefs(body); err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, map[string]string{"status": "ok"})
}

func (s *Server) handleAddDomain(w http.ResponseWriter, r *http.Request) {
	body, err := readBody(r)
	if err != nil {
		sendError(w, 400, "Invalid JSON")
		return
	}

	subdomain, _ := body["subdomain"].(string)
	target, _ := body["target"].(string)
	if subdomain == "" {
		sendError(w, 400, "Missing subdomain")
		return
	}
	if target == "" {
		sendError(w, 400, "Missing target")
		return
	}

	config, _ := s.storage.GetConfig()
	baseDomain, _ := config["base_domain"].(string)
	if baseDomain == "" {
		sendError(w, 400, "Base domain not configured")
		return
	}

	fqdn := subdomain
	if !strings.HasSuffix(subdomain, baseDomain) {
		fqdn = subdomain + "." + baseDomain
	}

	entry, err := s.storage.AddDomain(fqdn, target)
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, entry)

	// Background DNS + cert issuance
	go func() {
		// Create A or CNAME record
		recordType, err := setDNSRecord(s.dnsRecords, fqdn, target)
		if err != nil {
			errMsg := fmt.Sprintf("%v", err)
			logbuf.Log("server", fmt.Sprintf("Setup failed for %s: %s", fqdn, errMsg))
			_ = s.storage.UpdateDomain(fqdn, map[string]any{"status": "error", "last_error": errMsg})
			return
		}
		logbuf.Log("server", fmt.Sprintf("%s record created: %s -> %s", recordType, fqdn, target))

		// Issue certificate
		if err := s.acmeClient.IssueCertificate(fqdn); err != nil {
			errMsg := fmt.Sprintf("%v", err)
			logbuf.Log("server", fmt.Sprintf("Setup failed for %s: %s", fqdn, errMsg))
			_ = s.storage.UpdateDomain(fqdn, map[string]any{"status": "error", "last_error": errMsg})
		}
	}()
}

func (s *Server) handleRemoveDomain(w http.ResponseWriter, r *http.Request) {
	subdomain, _ := url.PathUnescape(r.PathValue("sub"))

	// Remove DNS records
	removeDNSRecords(s.dnsRecords, subdomain)

	if err := s.storage.RemoveDomain(subdomain); err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, map[string]string{"status": "removed"})
}

func (s *Server) handleDomainPost(w http.ResponseWriter, r *http.Request) {
	if !s.isAdminAuthenticated(r) {
		sendError(w, 401, "Not authenticated")
		return
	}

	sub, _ := url.PathUnescape(r.PathValue("sub"))
	if strings.HasSuffix(sub, "/rotate") {
		subdomain := strings.TrimSuffix(sub, "/rotate")
		s.handleRotateToken(w, subdomain)
	} else if strings.HasSuffix(sub, "/target") {
		subdomain := strings.TrimSuffix(sub, "/target")
		s.handleUpdateTarget(w, r, subdomain)
	} else {
		sendError(w, 404, "Not found")
	}
}

func (s *Server) handleRotateToken(w http.ResponseWriter, subdomain string) {
	newToken, err := s.storage.RotateDomainToken(subdomain)
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, map[string]string{"subdomain": subdomain, "api_token": newToken})
}

func (s *Server) handleUpdateTarget(w http.ResponseWriter, r *http.Request, subdomain string) {
	body, err := readBody(r)
	if err != nil {
		sendError(w, 400, "Invalid JSON")
		return
	}

	target, _ := body["target"].(string)
	if target == "" {
		sendError(w, 400, "Missing target")
		return
	}

	removeDNSRecords(s.dnsRecords, subdomain)
	recordType, err := setDNSRecord(s.dnsRecords, subdomain, target)
	if err != nil {
		sendError(w, 500, fmt.Sprintf("Failed to update DNS: %v", err))
		return
	}
	logbuf.Log("server", fmt.Sprintf("%s record updated: %s -> %s", recordType, subdomain, target))

	if err := s.storage.UpdateDomain(subdomain, map[string]any{"target": target}); err != nil {
		sendError(w, 500, err.Error())
		return
	}
	sendJSON(w, 200, map[string]string{"status": "updated", "target": target})
}

// --- Info handlers ---

func (s *Server) handleGetLogs(w http.ResponseWriter, r *http.Request) {
	entries := logbuf.GetEntries()
	sendJSON(w, 200, map[string]any{"entries": entries})
}

func (s *Server) handleGetVersion(w http.ResponseWriter, r *http.Request) {
	sendJSON(w, 200, map[string]string{
		"product":        "certpost",
		"api_version":    "1.0",
		"server_version": version.Version,
	})
}

func (s *Server) handleGetSpec(w http.ResponseWriter, r *http.Request) {
	sendJSON(w, 200, openAPISpec)
}

func (s *Server) handleGetHelp(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Write([]byte(apiHelpText))
}

func (s *Server) handleTokenInfo(w http.ResponseWriter, r *http.Request) {
	token := extractBearerToken(r)
	if token == "" {
		sendError(w, 401, "Missing or invalid Authorization header")
		return
	}

	domains, err := s.storage.GetDomains()
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	for _, d := range domains {
		if d["api_token"] == token {
			sendJSON(w, 200, map[string]string{"domain": fmt.Sprintf("%v", d["subdomain"])})
			return
		}
	}
	sendError(w, 403, "Invalid token")
}

// --- Cert retrieval ---

func (s *Server) handleGetCert(w http.ResponseWriter, r *http.Request) {
	token := extractBearerToken(r)
	if token == "" {
		sendError(w, 401, "Missing or invalid Authorization header")
		return
	}

	subdomain, _ := url.PathUnescape(r.PathValue("domain"))
	if subdomain == "" {
		sendError(w, 400, "Missing subdomain")
		return
	}

	if !s.storage.VerifyDomainToken(subdomain, token) {
		sendError(w, 403, "Invalid token for this domain")
		return
	}

	cert, err := s.storage.GetCert(subdomain)
	if err != nil {
		sendError(w, 500, err.Error())
		return
	}
	if cert == nil {
		sendError(w, 404, fmt.Sprintf("No certificate found for %s", subdomain))
		return
	}
	sendJSON(w, 200, cert)
}

// --- Helpers ---

func isIPAddress(value string) bool {
	return net.ParseIP(value) != nil
}

func setDNSRecord(d dns.Provider, fqdn, target string) (string, error) {
	if isIPAddress(target) {
		_, err := d.SetARecord(fqdn, target)
		return "A", err
	}
	_, err := d.SetCNAMERecord(fqdn, target)
	return "CNAME", err
}

func removeDNSRecords(d dns.Provider, fqdn string) {
	_ = d.RemoveARecord(fqdn)
	_ = d.RemoveCNAMERecord(fqdn)
}

func extractBearerToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") {
		return ""
	}
	return auth[7:]
}

func readBody(r *http.Request) (map[string]any, error) {
	data, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	var result map[string]any
	return result, json.Unmarshal(data, &result)
}

// setSessionCookie writes (or, with maxAge < 0 and an empty value, clears) a
// session cookie with the server's standard attributes. maxAge of 0 makes a
// session cookie (no Max-Age); a negative maxAge deletes it.
func setSessionCookie(w http.ResponseWriter, name, value string, maxAge int, sameSite http.SameSite, secure bool) {
	http.SetCookie(w, &http.Cookie{
		Name:     name,
		Value:    value,
		Path:     "/",
		MaxAge:   maxAge,
		HttpOnly: true,
		SameSite: sameSite,
		Secure:   secure,
	})
}

func sendJSON(w http.ResponseWriter, code int, data any) {
	out, _ := json.MarshalIndent(data, "", "  ")
	out = append(out, '\n')
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	w.Write(out)
}

func sendError(w http.ResponseWriter, code int, message string) {
	sendJSON(w, code, map[string]string{"error": message})
}
