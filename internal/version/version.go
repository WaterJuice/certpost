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

// LicenceText is the Unlicense text shown by --license/--licence flags.
const LicenceText = `This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

For more information, please refer to <https://unlicense.org/>`
