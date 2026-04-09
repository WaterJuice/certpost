// ---------------------------------------------------------------------------------------
//
//	colour.go
//	---------
//
//	ANSI colour helpers for CLI output. Colours are only applied when stderr
//	is a terminal and NO_COLOR / TERM=dumb are not set. Colour scheme matches
//	Python 3.14's argparse theme.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created
//
// ---------------------------------------------------------------------------------------
package colour

import (
	"os"
)

// ANSI colour codes matching Python 3.14 argparse theme.
var (
	Heading  = "\033[1;34m" // bold blue — section headers
	Prog     = "\033[1;35m" // bold magenta — program name
	LongOpt  = "\033[1;36m" // bold cyan — --long-options
	Label    = "\033[1;33m" // bold yellow — <placeholders>
	ShortOpt = "\033[1;32m" // bold green — short options / commands
	Reset    = "\033[0m"
)

func init() {
	if !shouldColourise() {
		Heading = ""
		Prog = ""
		LongOpt = ""
		Label = ""
		ShortOpt = ""
		Reset = ""
	}
}

func shouldColourise() bool {
	if os.Getenv("NO_COLOR") != "" {
		return false
	}
	if os.Getenv("TERM") == "dumb" {
		return false
	}
	fi, err := os.Stdout.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}
