// ---------------------------------------------------------------------------------------
//
//	provider.go
//	-----------
//
//	DNS provider interface. Defines the contract that DNS backends must implement
//	for managing TXT, A, and CNAME records.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package dns

// Provider is the interface that DNS backends must implement.
type Provider interface {
	SetTXTRecord(name, value string) (string, error)
	RemoveTXTRecord(name string) error
	SetARecord(name, ip string) (string, error)
	RemoveARecord(name string) error
	SetCNAMERecord(name, target string) (string, error)
	RemoveCNAMERecord(name string) error
}
