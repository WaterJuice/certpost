// ---------------------------------------------------------------------------------------
//
//	cryptoutil.go
//	-------------
//
//	RSA key generation, CSR creation, JWS building, certificate parsing, and
//	related crypto utilities. All operations use Go's native crypto libraries —
//	no external dependencies or openssl subprocess.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package cryptoutil

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"time"
)

// B64URL encodes data as base64url without padding.
func B64URL(data []byte) string {
	return base64.RawURLEncoding.EncodeToString(data)
}

// GenerateRSAKey generates an RSA private key of the given bit size and returns it as a PEM string.
func GenerateRSAKey(bits int) (string, error) {
	key, err := rsa.GenerateKey(rand.Reader, bits)
	if err != nil {
		return "", fmt.Errorf("generate RSA key: %w", err)
	}
	derBytes := x509.MarshalPKCS1PrivateKey(key)
	pemBlock := &pem.Block{Type: "RSA PRIVATE KEY", Bytes: derBytes}
	return string(pem.EncodeToMemory(pemBlock)), nil
}

// ParseRSAKey parses a PEM-encoded RSA private key.
func ParseRSAKey(pemStr string) (*rsa.PrivateKey, error) {
	block, _ := pem.Decode([]byte(pemStr))
	if block == nil {
		return nil, fmt.Errorf("no PEM block found")
	}
	// Try PKCS1 first, then PKCS8
	key, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err == nil {
		return key, nil
	}
	parsed, err2 := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err2 != nil {
		return nil, fmt.Errorf("parse RSA key: %w (pkcs1: %v)", err2, err)
	}
	rsaKey, ok := parsed.(*rsa.PrivateKey)
	if !ok {
		return nil, fmt.Errorf("key is not RSA")
	}
	return rsaKey, nil
}

// CreateCSR creates a Certificate Signing Request for the given domains.
// Returns the CSR in DER format.
func CreateCSR(keyPEM string, domains []string) ([]byte, error) {
	key, err := ParseRSAKey(keyPEM)
	if err != nil {
		return nil, fmt.Errorf("parse key for CSR: %w", err)
	}

	template := &x509.CertificateRequest{
		Subject:  pkix.Name{CommonName: domains[0]},
		DNSNames: domains,
	}

	csrDER, err := x509.CreateCertificateRequest(rand.Reader, template, key)
	if err != nil {
		return nil, fmt.Errorf("create CSR: %w", err)
	}
	return csrDER, nil
}

// RSAPublicNumbers returns the modulus (n) and exponent (e) of an RSA key as base64url strings.
func RSAPublicNumbers(keyPEM string) (n string, e string, err error) {
	key, err := ParseRSAKey(keyPEM)
	if err != nil {
		return "", "", err
	}

	// Modulus — big-endian bytes, no leading zero padding
	nBytes := key.PublicKey.N.Bytes()
	nB64 := B64URL(nBytes)

	// Exponent — big-endian bytes
	eBig := big.NewInt(int64(key.PublicKey.E))
	eBytes := eBig.Bytes()
	eB64 := B64URL(eBytes)

	return nB64, eB64, nil
}

// SignRS256 signs data using RSASSA-PKCS1-v1_5 with SHA-256.
func SignRS256(keyPEM string, data []byte) ([]byte, error) {
	key, err := ParseRSAKey(keyPEM)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(data)
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, hash[:])
	if err != nil {
		return nil, fmt.Errorf("RS256 sign: %w", err)
	}
	return sig, nil
}

// BuildJWS builds a JWS (JSON Web Signature) for ACME requests.
func BuildJWS(url string, payload any, nonce, accountKeyPEM, kid string) (string, error) {
	// Header
	header := map[string]any{
		"alg":   "RS256",
		"nonce": nonce,
		"url":   url,
	}
	if kid != "" {
		header["kid"] = kid
	} else {
		n, e, err := RSAPublicNumbers(accountKeyPEM)
		if err != nil {
			return "", fmt.Errorf("get public numbers for JWK: %w", err)
		}
		header["jwk"] = map[string]string{
			"kty": "RSA",
			"n":   n,
			"e":   e,
		}
	}

	headerJSON, _ := json.Marshal(header)
	headerB64 := B64URL(headerJSON)

	// Payload
	var payloadB64 string
	if payload == nil {
		// POST-as-GET: empty payload
		payloadB64 = ""
	} else {
		payloadJSON, _ := json.Marshal(payload)
		payloadB64 = B64URL(payloadJSON)
	}

	// Signature
	signingInput := []byte(headerB64 + "." + payloadB64)
	sig, err := SignRS256(accountKeyPEM, signingInput)
	if err != nil {
		return "", err
	}
	sigB64 := B64URL(sig)

	result := map[string]string{
		"protected": headerB64,
		"payload":   payloadB64,
		"signature": sigB64,
	}
	out, _ := json.Marshal(result)
	return string(out), nil
}

// JWKThumbprint computes the JWK thumbprint (SHA-256) of an RSA account key.
func JWKThumbprint(accountKeyPEM string) (string, error) {
	n, e, err := RSAPublicNumbers(accountKeyPEM)
	if err != nil {
		return "", err
	}
	// Canonical JSON with sorted keys
	jwkJSON := fmt.Sprintf(`{"e":"%s","kty":"RSA","n":"%s"}`, e, n)
	hash := sha256.Sum256([]byte(jwkJSON))
	return B64URL(hash[:]), nil
}

// DNSChallengeValue computes the DNS-01 challenge value for a given token and account key.
func DNSChallengeValue(token, accountKeyPEM string) (string, error) {
	tp, err := JWKThumbprint(accountKeyPEM)
	if err != nil {
		return "", err
	}
	keyAuth := token + "." + tp
	hash := sha256.Sum256([]byte(keyAuth))
	return B64URL(hash[:]), nil
}

// ParseCertExpiry parses the expiry date from a PEM certificate. Returns ISO 8601 timestamp.
func ParseCertExpiry(certPEM string) (string, error) {
	block, _ := pem.Decode([]byte(certPEM))
	if block == nil {
		return "", fmt.Errorf("no PEM block found in certificate")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return "", fmt.Errorf("parse certificate: %w", err)
	}
	return cert.NotAfter.UTC().Format(time.RFC3339), nil
}
