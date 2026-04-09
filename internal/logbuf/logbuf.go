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
	mu    sync.Mutex
	ring  [maxEntries]Entry
	head  int // next write position
	count int // number of entries stored (up to maxEntries)
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
	ring[head] = entry
	head = (head + 1) % maxEntries
	if count < maxEntries {
		count++
	}
	mu.Unlock()

	fmt.Fprintf(os.Stderr, "  [%s] %s\n", source, message)
}

// GetEntries returns a copy of all log entries (oldest first).
func GetEntries() []Entry {
	mu.Lock()
	defer mu.Unlock()
	result := make([]Entry, count)
	start := (head - count + maxEntries) % maxEntries
	for i := 0; i < count; i++ {
		result[i] = ring[(start+i)%maxEntries]
	}
	return result
}
