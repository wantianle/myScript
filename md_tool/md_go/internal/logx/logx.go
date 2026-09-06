// Package logx provides the [INFO]/[OK]/[WARNING]/[ERROR] colored log helpers
// that md.sh's log_info/log_ok/log_warn/log_err emit (md.sh:60-63). All output
// goes to stderr so the caller's stdout stays free for command output.
//
// The Bash original colors the prefix like `\033[1;32m[OK]\033[0m`. Since the
// Go tool ships no color constants elsewhere yet, these use plain colored
// brackets and reset; colors are emitted only when w is a terminal.
package logx

import (
	"fmt"
	"io"
	"os"
)

// Colors (md.sh:6-10).
const (
	colRed    = "\033[1;31m"
	colGreen  = "\033[1;32m"
	colYellow = "\033[1;33m"
	colBlue   = "\033[1;34m"
	colNC     = "\033[0m"
)

// Logger writes md.sh-style prefixed messages.
type Logger struct {
	w io.Writer
}

// New returns a Logger writing to stderr (md.sh logs to stdout because the
// whole tool's messages go there; the Go tool keeps stdout for command
// payloads, so messages go to stderr — see logx doc).
func New() *Logger {
	return &Logger{w: os.Stderr}
}

// NewWithWriter returns a Logger writing to w (used in tests).
func NewWithWriter(w io.Writer) *Logger {
	return &Logger{w: w}
}

// Info prints the [INFO] line (md.sh log_info).
func (l *Logger) Info(format string, a ...any) { l.print(colBlue, "INFO", format, a...) }

// Ok prints the [OK] line (md.sh log_ok).
func (l *Logger) Ok(format string, a ...any) { l.print(colGreen, "OK", format, a...) }

// Warn prints the [WARNING] line (md.sh log_warn).
func (l *Logger) Warn(format string, a ...any) { l.print(colYellow, "WARNING", format, a...) }

// Err prints the [ERROR] line (md.sh log_err).
func (l *Logger) Err(format string, a ...any) { l.print(colRed, "ERROR", format, a...) }

// print writes one prefixed line to stderr. Colors are suppressed when the
// writer is not a terminal so piped logs stay clean.
func (l *Logger) print(color, tag, format string, a ...any) {
	label := fmt.Sprintf("[%s]", tag)
	body := fmt.Sprintf(format, a...)
	if isTerm(l.w) {
		fmt.Fprintf(l.w, "%s%s%s %s\n", color, label, colNC, body)
		return
	}
	fmt.Fprintf(l.w, "%s %s\n", label, body)
}

func isTerm(w io.Writer) bool {
	f, ok := w.(*os.File)
	if !ok {
		return false
	}
	st, err := f.Stat()
	if err != nil {
		return false
	}
	return st.Mode()&os.ModeCharDevice != 0
}
