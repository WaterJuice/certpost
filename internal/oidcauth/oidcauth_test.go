package oidcauth

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

// makeIDToken builds a JWT-shaped id_token whose payload encodes the given
// claims. The header and signature segments are placeholders — the package
// decodes the payload only.
func makeIDToken(t *testing.T, claims map[string]any) string {
	t.Helper()
	payload, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	enc := base64.RawURLEncoding.EncodeToString
	return enc([]byte(`{"alg":"RS256"}`)) + "." + enc(payload) + "." + enc([]byte("sig"))
}

// providerServer spins up a fake OIDC provider: a discovery document advertising
// its own authorise/token endpoints, plus a token endpoint returning idToken.
func providerServer(t *testing.T, idToken string) *httptest.Server {
	t.Helper()
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/.well-known/openid-configuration":
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{
				"issuer":                 srv.URL,
				"authorization_endpoint": srv.URL + "/authorise",
				"token_endpoint":         srv.URL + "/token",
			})
		case "/token":
			_ = r.ParseForm()
			if r.FormValue("grant_type") != "authorization_code" || r.FormValue("code") != "the-code" {
				http.Error(w, "bad request", http.StatusBadRequest)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"id_token": idToken})
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestPKCEChallengeIsS256OfVerifier(t *testing.T) {
	verifier, challenge := pkcePair()
	sum := sha256.Sum256([]byte(verifier))
	want := base64.RawURLEncoding.EncodeToString(sum[:])
	if challenge != want {
		t.Errorf("challenge = %q, want base64url-nopad(sha256(verifier)) = %q", challenge, want)
	}
	if strings.ContainsAny(challenge, "=+/") {
		t.Errorf("challenge %q is not URL-safe nopad", challenge)
	}
}

func TestLoginURLParams(t *testing.T) {
	srv := providerServer(t, "")
	a := New(Config{
		Issuer:       srv.URL + "/", // trailing slash should be stripped
		ClientID:     "cid",
		ClientSecret: "secret",
		RedirectURI:  "http://127.0.0.1:8089/auth-callback",
	})
	raw, err := a.LoginURL(context.Background())
	if err != nil {
		t.Fatalf("LoginURL: %v", err)
	}
	if !strings.HasPrefix(raw, srv.URL+"/authorise?") {
		t.Fatalf("unexpected authorise URL: %q", raw)
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	q := u.Query()
	checks := map[string]string{
		"client_id":             "cid",
		"redirect_uri":          "http://127.0.0.1:8089/auth-callback",
		"response_type":         "code",
		"scope":                 "openid",
		"code_challenge_method": "S256",
	}
	for k, want := range checks {
		if got := q.Get(k); got != want {
			t.Errorf("%s = %q, want %q", k, got, want)
		}
	}
	if q.Get("state") == "" {
		t.Error("state is empty")
	}
	if q.Get("code_challenge") == "" {
		t.Error("code_challenge is empty")
	}

	// The state must now be pending.
	a.mu.Lock()
	_, pending := a.pending[q.Get("state")]
	a.mu.Unlock()
	if !pending {
		t.Error("state was not recorded as pending")
	}
}

func TestClaimsFromIDTokenReadsPreferredUsername(t *testing.T) {
	tok := makeIDToken(t, map[string]any{"preferred_username": "alice"})
	c, err := claimsFromIDToken(tok)
	if err != nil {
		t.Fatal(err)
	}
	if c.PreferredUsername != "alice" {
		t.Errorf("PreferredUsername = %q, want alice", c.PreferredUsername)
	}
}

// completeAgainst runs the full Complete flow against a fake provider (minting a
// real pending state first via LoginURL).
func completeAgainst(t *testing.T, cfg Config, idToken string) (Session, error) {
	t.Helper()
	srv := providerServer(t, idToken)
	cfg.Issuer = srv.URL
	a := New(cfg)
	// Mint a real pending state through the public entry point.
	raw, err := a.LoginURL(context.Background())
	if err != nil {
		t.Fatalf("LoginURL: %v", err)
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	state := u.Query().Get("state")
	return a.Complete(context.Background(), "the-code", state)
}

func TestCompleteAcceptsAuthorisedUser(t *testing.T) {
	tok := makeIDToken(t, map[string]any{"preferred_username": "bob"})
	sess, err := completeAgainst(t, Config{
		ClientID: "c", ClientSecret: "s", AuthorisedUsers: []string{"alice", "bob"},
	}, tok)
	if err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if sess.Username != "bob" {
		t.Errorf("Username = %q, want bob", sess.Username)
	}
}

func TestCompleteFallsBackToNickname(t *testing.T) {
	// A provider (e.g. GitLab) that carries the username in `nickname` rather
	// than `preferred_username` still resolves and matches the allow-list.
	tok := makeIDToken(t, map[string]any{"nickname": "bob"})
	sess, err := completeAgainst(t, Config{
		ClientID: "c", ClientSecret: "s", AuthorisedUsers: []string{"bob"},
	}, tok)
	if err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if sess.Username != "bob" {
		t.Errorf("Username = %q, want bob", sess.Username)
	}
}

func TestCompleteRejectsUnauthorisedUser(t *testing.T) {
	tok := makeIDToken(t, map[string]any{"preferred_username": "carol"})
	_, err := completeAgainst(t, Config{
		ClientID: "c", ClientSecret: "s", AuthorisedUsers: []string{"alice", "bob"},
	}, tok)
	if !errors.Is(err, ErrForbidden) {
		t.Errorf("err = %v, want ErrForbidden", err)
	}
}

func TestCompleteUnknownState(t *testing.T) {
	srv := providerServer(t, "")
	a := New(Config{Issuer: srv.URL, ClientID: "c", ClientSecret: "s"})
	_, err := a.Complete(context.Background(), "the-code", "never-minted")
	if !errors.Is(err, ErrInvalidState) {
		t.Errorf("err = %v, want ErrInvalidState", err)
	}
}

func TestStateIsSingleUse(t *testing.T) {
	tok := makeIDToken(t, map[string]any{"preferred_username": "dave"})
	srv := providerServer(t, tok)

	a := New(Config{Issuer: srv.URL, ClientID: "c", ClientSecret: "s", AuthorisedUsers: []string{"dave"}})
	raw, err := a.LoginURL(context.Background())
	if err != nil {
		t.Fatalf("LoginURL: %v", err)
	}
	u, _ := url.Parse(raw)
	state := u.Query().Get("state")

	if _, err := a.Complete(context.Background(), "the-code", state); err != nil {
		t.Fatalf("first Complete: %v", err)
	}
	if _, err := a.Complete(context.Background(), "the-code", state); !errors.Is(err, ErrInvalidState) {
		t.Errorf("second Complete err = %v, want ErrInvalidState", err)
	}
}

func TestSessionRoundTrip(t *testing.T) {
	a := New(Config{ClientID: "c", ClientSecret: "s"})
	sid := a.StartSession(Session{Username: "erin"})
	if sid == "" {
		t.Fatal("empty sid")
	}
	got, ok := a.SessionFor(sid)
	if !ok || got.Username != "erin" {
		t.Errorf("SessionFor = %+v, %v; want erin session", got, ok)
	}
	a.EndSession(sid)
	if _, ok := a.SessionFor(sid); ok {
		t.Error("session survived EndSession")
	}
}
