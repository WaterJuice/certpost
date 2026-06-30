// ---------------------------------------------------------------------------------------
//
//	oidcauth.go
//	-----------
//
//	An authentication-only OpenID Connect login, using the authorisation-code
//	flow with PKCE. The configured provider is used purely as an identity
//	provider: no provider API is ever called and no access token is stored. The
//	id_token returned on the token back-channel carries the username
//	(`preferred_username`) we need, and that is the end of the provider's
//	involvement.
//
//	The authorise/token endpoints are learned at run time from the issuer's
//	OpenID Connect discovery document (`<issuer>/.well-known/openid-configuration`),
//	so the only URL the operator supplies is the issuer. Because every
//	standards-compliant OIDC provider publishes that document, the flow is not
//	tied to any one provider's URL layout — pointing `issuer` at any compliant
//	provider works without code changes. Discovery is performed lazily on first
//	login and cached, so a provider that is briefly unreachable at start-up does
//	not stop the rest of the service.
//
//	Access is gated by an explicit allow-list: a completed login is only
//	accepted when its `preferred_username` appears in AuthorisedUsers.
//
//	The package is stdlib-only and framework-agnostic: it owns all of the
//	protocol logic (discovery, state, PKCE, token exchange, id_token decode) so
//	callers only wire up the two HTTP endpoints (login redirect and callback)
//	and a session cookie.
//
//	Sessions are held in memory and therefore reset when the process
//	restarts; users simply log in again.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Jun 2026 - Created — a provider-agnostic OIDC login backend for 1.1
//
// ---------------------------------------------------------------------------------------
package oidcauth

// ---------------------------------------------------------------------------------------
//
//	Imports
//
// ---------------------------------------------------------------------------------------

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Sentinel errors returned by Complete.
var (
	// ErrInvalidState is returned when the callback's state does not match a
	// pending login (unknown, replayed, or forged).
	ErrInvalidState = errors.New("oidcauth: invalid or expired state")
	// ErrForbidden is returned when the user authenticated but is not in the
	// configured AuthorisedUsers allow-list.
	ErrForbidden = errors.New("oidcauth: user not permitted")
)

// httpTimeout bounds the back-channel requests (discovery and token exchange).
const httpTimeout = 10 * time.Second

// pendingTTL is how long a started-but-unfinished login is remembered. A user
// who is redirected to the provider and never returns leaves a pending entry
// behind; entries older than this are dropped on the next LoginURL so the map
// stays bounded.
const pendingTTL = 10 * time.Minute

// Config holds the OAuth application credentials and policy.
type Config struct {
	// Issuer is the OIDC issuer URL of the provider, e.g.
	// "https://sso.example.com" (some providers add a path, such as a realm).
	// A trailing slash is tolerated. The authorise/token endpoints are learned
	// from "<issuer>/.well-known/openid-configuration".
	Issuer string
	// ClientID and ClientSecret are the OAuth application credentials
	// (a confidential client).
	ClientID     string
	ClientSecret string
	// RedirectURI is the exact callback URL registered with the provider; it
	// must byte-match the value the provider has on file.
	RedirectURI string
	// AuthorisedUsers is the allow-list of `preferred_username` values that may
	// log in. A login whose username is absent is rejected with ErrForbidden.
	AuthorisedUsers []string
}

// Session is the identity established by a completed login.
type Session struct {
	Username string
}

// pendingLogin is a started-but-unfinished login: the PKCE verifier kept for the
// matching callback, plus when it began so stale entries can be pruned.
type pendingLogin struct {
	verifier string
	created  time.Time
}

// endpoints are the provider URLs learned from the discovery document.
type endpoints struct {
	authoriseURL string
	tokenURL     string
}

// Auth drives the login flow and holds the in-memory pending/session state.
type Auth struct {
	cfg          Config
	discoveryURL string // <issuer>/.well-known/openid-configuration (built once in New)
	callbackPath string // path component of RedirectURI (parsed once in New)
	redirectTLS  bool   // whether RedirectURI is https (parsed once in New)
	allowed      map[string]struct{}
	client       *http.Client

	mu       sync.Mutex
	pending  map[string]pendingLogin // state -> PKCE verifier + start time (consumed on callback)
	sessions map[string]Session      // sid -> session

	epMu sync.Mutex // guards the cached endpoints (separate from mu so a slow
	ep   *endpoints // discovery fetch never blocks session lookups)
}

// New builds an Auth from cfg. The trailing slash on Issuer is stripped so URL
// construction is predictable, the discovery URL is built from it, and
// RedirectURI is parsed once for the callback path and scheme. No network call
// is made here — discovery happens lazily on the first login.
func New(cfg Config) *Auth {
	cfg.Issuer = strings.TrimRight(cfg.Issuer, "/")
	path, isTLS := "/auth-callback", false
	if u, err := url.Parse(cfg.RedirectURI); err == nil {
		if u.Path != "" {
			path = u.Path
		}
		isTLS = u.Scheme == "https"
	}
	allowed := make(map[string]struct{}, len(cfg.AuthorisedUsers))
	for _, u := range cfg.AuthorisedUsers {
		allowed[u] = struct{}{}
	}
	return &Auth{
		cfg:          cfg,
		discoveryURL: cfg.Issuer + "/.well-known/openid-configuration",
		callbackPath: path,
		redirectTLS:  isTLS,
		allowed:      allowed,
		client:       &http.Client{Timeout: httpTimeout},
		pending:      make(map[string]pendingLogin),
		sessions:     make(map[string]Session),
	}
}

// CallbackPath returns the path component of the configured RedirectURI, which
// is where the OAuth callback must be served so it byte-matches the redirect
// the provider was given. Falls back to "/auth-callback" when RedirectURI has
// no path.
func (a *Auth) CallbackPath() string { return a.callbackPath }

// RedirectIsHTTPS reports whether the configured RedirectURI uses https, used
// to decide whether the session cookie should carry the Secure attribute.
func (a *Auth) RedirectIsHTTPS() bool { return a.redirectTLS }

// discover returns the provider's authorise/token endpoints, fetching the
// OpenID Connect discovery document on first use and caching the result. The
// HTTP fetch runs without epMu held so a slow provider cannot wedge concurrent
// logins; a lost race just fetches twice and stores the same (idempotent) data.
func (a *Auth) discover(ctx context.Context) (endpoints, error) {
	a.epMu.Lock()
	cached := a.ep
	a.epMu.Unlock()
	if cached != nil {
		return *cached, nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, a.discoveryURL, nil)
	if err != nil {
		return endpoints{}, err
	}
	req.Header.Set("Accept", "application/json")

	resp, err := a.client.Do(req)
	if err != nil {
		return endpoints{}, fmt.Errorf("oidcauth: fetching discovery document: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return endpoints{}, err
	}
	if resp.StatusCode != http.StatusOK {
		return endpoints{}, fmt.Errorf("oidcauth: discovery document returned %s", resp.Status)
	}

	var doc struct {
		AuthorizationEndpoint string `json:"authorization_endpoint"`
		TokenEndpoint         string `json:"token_endpoint"`
	}
	if err := json.Unmarshal(body, &doc); err != nil {
		return endpoints{}, fmt.Errorf("oidcauth: decoding discovery document: %w", err)
	}
	if doc.AuthorizationEndpoint == "" || doc.TokenEndpoint == "" {
		return endpoints{}, errors.New("oidcauth: discovery document missing authorise/token endpoint")
	}

	ep := endpoints{authoriseURL: doc.AuthorizationEndpoint, tokenURL: doc.TokenEndpoint}
	a.epMu.Lock()
	a.ep = &ep
	a.epMu.Unlock()
	return ep, nil
}

// LoginURL mints a fresh state + PKCE verifier, records the pending login, and
// returns the provider's authorise URL to redirect the browser to. It resolves
// the authorise endpoint via discovery, so it can fail if the provider is
// unreachable. The scope is "openid" only — we want an id_token and nothing more.
func (a *Auth) LoginURL(ctx context.Context) (string, error) {
	ep, err := a.discover(ctx)
	if err != nil {
		return "", err
	}

	state := randToken()
	verifier, challenge := pkcePair()

	now := time.Now()
	a.mu.Lock()
	for s, p := range a.pending { // drop abandoned logins so the map stays bounded
		if now.Sub(p.created) > pendingTTL {
			delete(a.pending, s)
		}
	}
	a.pending[state] = pendingLogin{verifier: verifier, created: now}
	a.mu.Unlock()

	q := url.Values{
		"client_id":             {a.cfg.ClientID},
		"redirect_uri":          {a.cfg.RedirectURI},
		"response_type":         {"code"},
		"scope":                 {"openid"},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}
	return ep.authoriseURL + "?" + q.Encode(), nil
}

// Complete validates the callback state, exchanges the code for tokens, decodes
// the id_token to establish identity, and enforces the AuthorisedUsers
// allow-list. The state is single-use: it is consumed whether or not the
// exchange succeeds.
func (a *Auth) Complete(ctx context.Context, code, state string) (Session, error) {
	a.mu.Lock()
	p, ok := a.pending[state]
	if ok {
		delete(a.pending, state)
	}
	a.mu.Unlock()
	if !ok || time.Since(p.created) > pendingTTL {
		return Session{}, ErrInvalidState
	}
	verifier := p.verifier

	ep, err := a.discover(ctx)
	if err != nil {
		return Session{}, err
	}

	idToken, err := a.exchange(ctx, ep.tokenURL, code, verifier)
	if err != nil {
		return Session{}, err
	}

	claims, err := claimsFromIDToken(idToken)
	if err != nil {
		return Session{}, err
	}

	username := claims.PreferredUsername
	if username == "" {
		username = claims.Nickname
	}
	if username == "" {
		return Session{}, errors.New("oidcauth: id_token carried no username (preferred_username/nickname)")
	}
	if _, ok := a.allowed[username]; !ok {
		return Session{}, fmt.Errorf("%w: %q", ErrForbidden, username)
	}

	return Session{Username: username}, nil
}

// exchange POSTs the authorisation code to the token endpoint and returns the
// raw id_token.
func (a *Auth) exchange(ctx context.Context, tokenURL, code, verifier string) (string, error) {
	form := url.Values{
		"client_id":     {a.cfg.ClientID},
		"client_secret": {a.cfg.ClientSecret},
		"code":          {code},
		"grant_type":    {"authorization_code"},
		"redirect_uri":  {a.cfg.RedirectURI},
		"code_verifier": {verifier},
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")

	resp, err := a.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", err
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("oidcauth: token endpoint returned %s", resp.Status)
	}

	var tok struct {
		IDToken string `json:"id_token"`
	}
	if err := json.Unmarshal(body, &tok); err != nil {
		return "", fmt.Errorf("oidcauth: decoding token response: %w", err)
	}
	if tok.IDToken == "" {
		return "", errors.New("oidcauth: token response carried no id_token")
	}
	return tok.IDToken, nil
}

// StartSession stores s under a fresh opaque session id and returns the id, to
// be set as the session cookie value.
func (a *Auth) StartSession(s Session) string {
	sid := randToken()
	a.mu.Lock()
	a.sessions[sid] = s
	a.mu.Unlock()
	return sid
}

// SessionFor returns the session for sid, if any.
func (a *Auth) SessionFor(sid string) (Session, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()
	s, ok := a.sessions[sid]
	return s, ok
}

// EndSession forgets the session for sid (logout). Unknown sids are ignored.
func (a *Auth) EndSession(sid string) {
	a.mu.Lock()
	delete(a.sessions, sid)
	a.mu.Unlock()
}

// idClaims is the subset of the id_token payload we use. OIDC providers put the
// username in the standard `preferred_username` claim; some (e.g. GitLab) carry
// it in `nickname` instead, so we accept either.
type idClaims struct {
	PreferredUsername string `json:"preferred_username"`
	Nickname          string `json:"nickname"`
}

// claimsFromIDToken decodes the payload (middle segment) of a JWT id_token. The
// signature is intentionally not verified: the token arrives directly from the
// token endpoint over the TLS back-channel, so its provenance is already
// established and re-verifying the signature would buy nothing.
func claimsFromIDToken(idToken string) (idClaims, error) {
	parts := strings.Split(idToken, ".")
	if len(parts) != 3 {
		return idClaims{}, errors.New("oidcauth: id_token is not a JWT")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return idClaims{}, fmt.Errorf("oidcauth: decoding id_token payload: %w", err)
	}
	var c idClaims
	if err := json.Unmarshal(payload, &c); err != nil {
		return idClaims{}, fmt.Errorf("oidcauth: parsing id_token claims: %w", err)
	}
	return c, nil
}

// pkcePair returns a random code verifier and its S256 challenge
// (base64url-nopad(sha256(verifier))).
func pkcePair() (verifier, challenge string) {
	verifier = randToken()
	sum := sha256.Sum256([]byte(verifier))
	challenge = base64.RawURLEncoding.EncodeToString(sum[:])
	return verifier, challenge
}

// randToken returns a 32-byte cryptographically-random, URL-safe token.
func randToken() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand should never fail; if it does there is no safe way to
		// continue minting unguessable tokens.
		panic("oidcauth: crypto/rand failed: " + err.Error())
	}
	return base64.RawURLEncoding.EncodeToString(b)
}
