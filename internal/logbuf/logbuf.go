// ---------------------------------------------------------------------------------------
//
//	logbuf.go
//	---------
//
//	In-memory ring buffer log for certpost. Captures log messages (max 200) so
//	they can be viewed in the admin panel. Also prints to stderr.
//
//	(c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
//
//	Version History
//	---------------
//	Apr 2026 - Created (Go rewrite)
//
// ---------------------------------------------------------------------------------------
package logbuf

import (
	"fmt"
	"os"
	"sync"
	"time"
)

const maxEntries = 200

// Entry represents a single log entry.
type Entry struct {
	Timestamp string `json:"timestamp"`
	Source    string `json:"source"`
	Message   string `json:"message"`
}

var (
	mu      sync.Mutex
	entries []Entry
)

// Log adds a log entry and prints to stderr.
func Log(source, message string) {
	timestamp := time.Now().UTC().Format(time.RFC3339)
	entry := Entry{
		Timestamp: timestamp,
		Source:    source,
		Message:   message,
	}

	mu.Lock()
	entries = append(entries, entry)
	if len(entries) > maxEntries {
		entries = entries[len(entries)-maxEntries:]
	}
	mu.Unlock()

	fmt.Fprintf(os.Stderr, "  [%s] %s\n", source, message)
}

// GetEntries returns a copy of all log entries (newest last).
func GetEntries() []Entry {
	mu.Lock()
	defer mu.Unlock()
	result := make([]Entry, len(entries))
	copy(result, entries)
	return result
}
