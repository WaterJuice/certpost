// ---------------------------------------------------------------------------------------
//
//	embed.go
//	--------
//
//	Embeds the admin panel HTML into the binary at compile time via go:embed.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package web

import _ "embed"

//go:embed index.html
var AdminHTML []byte
