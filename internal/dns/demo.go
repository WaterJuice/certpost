// ---------------------------------------------------------------------------------------
//
//	demo.go
//	-------
//
//	No-op DNS provider used by `certpost-server run --demo` for local GUI
//	preview. All record operations return success without making any
//	network call, so the admin panel can be explored without touching a
//	real DNS provider.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
// ---------------------------------------------------------------------------------------
package dns

import "github.com/WaterJuice/certpost/internal/logbuf"

type demoProvider struct{}

func (d *demoProvider) SetTXTRecord(name, value string) (string, error) {
	logbuf.Log("dns-demo", "SetTXTRecord "+name+" (no-op)")
	return "demo-txt-" + name, nil
}

func (d *demoProvider) RemoveTXTRecord(name string) error {
	logbuf.Log("dns-demo", "RemoveTXTRecord "+name+" (no-op)")
	return nil
}

func (d *demoProvider) SetARecord(name, ip string) (string, error) {
	logbuf.Log("dns-demo", "SetARecord "+name+" -> "+ip+" (no-op)")
	return "demo-a-" + name, nil
}

func (d *demoProvider) RemoveARecord(name string) error {
	logbuf.Log("dns-demo", "RemoveARecord "+name+" (no-op)")
	return nil
}

func (d *demoProvider) SetCNAMERecord(name, target string) (string, error) {
	logbuf.Log("dns-demo", "SetCNAMERecord "+name+" -> "+target+" (no-op)")
	return "demo-cname-" + name, nil
}

func (d *demoProvider) RemoveCNAMERecord(name string) error {
	logbuf.Log("dns-demo", "RemoveCNAMERecord "+name+" (no-op)")
	return nil
}
