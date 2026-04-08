// ---------------------------------------------------------------------------------------
//
//	version.go
//	----------
//
//	Application version string. Set at build time via ldflags:
//	  go build -ldflags "-X .../version.Version=1.0.0"
//	Falls back to "dev" when not set.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package version

// Version is the application version, set at build time. Defaults to "dev".
var Version = "dev"
