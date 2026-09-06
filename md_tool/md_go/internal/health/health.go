// Package health implements the read-only probe helpers for the `md check`
// command, faithful to md.sh's disk::usage / disk_free_gb / disk_used_pct and
// the keep-read-only segments of disk::diagnose (md.sh:1083-1112, 1132-1194).
//
// The G3.0 full-feature assessment demoted this layer: it no longer returns
// the 1-7 repair codes of md.sh disk::diagnose and never triggers disk::fix.
// Only the read-only probes are kept — mount state, content access, read-only
// degradation, the MDRIVE_DATA_ROOT symlink target, and free/used space
// warnings. Every function is pure (it parses captured command-output strings)
// so it is unit-testable without a real disk.
package health

import (
	"strconv"
	"strings"
)

// Percent parses a `df -h` %used token (leading/trailing space and a trailing
// '%' tolerated) into an int. ok=false when the value is not a plain integer,
// which md.sh disk::usage treats as a read failure (return 2).
func Percent(token string) (int, bool) {
	text := strings.TrimSpace(token)
	text = strings.TrimSuffix(text, "%")
	n, err := strconv.Atoi(text)
	if err != nil {
		return 0, false
	}
	return n, true
}

// FreeGB parses a `df -BG` available-GB token (trailing 'G' tolerated) into an
// int. ok=false when unreadable (md.sh disk_free_gb returns empty on failure,
// which callers treat as "cannot determine").
func FreeGB(token string) (int, bool) {
	text := strings.TrimSpace(token)
	text = strings.TrimSuffix(text, "G")
	n, err := strconv.Atoi(text)
	if err != nil {
		return 0, false
	}
	return n, true
}

// DataRow returns the second non-empty line of a `df` command's output — the
// data row the awk `NR==2` selects (the first line is the header). Empty when
// fewer than two non-empty lines exist.
func DataRow(dfOutput string) string {
	var rows []string
	for _, line := range strings.Split(dfOutput, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			rows = append(rows, line)
		}
	}
	if len(rows) < 2 {
		return ""
	}
	return rows[1]
}

// RowUsedPct extracts the %used column (field 5 of the df -h data row) and
// returns it as an int. ok=false on any parse failure.
func RowUsedPct(dfOutput string) (int, bool) {
	row := DataRow(dfOutput)
	if row == "" {
		return 0, false
	}
	fields := strings.Fields(row)
	if len(fields) < 5 {
		return 0, false
	}
	return Percent(fields[4])
}

// RowFreeGB extracts the available-GB column (field 4 of a `df -BG` data row)
// and returns it as an int. ok=false on any parse failure.
func RowFreeGB(dfOutput string) (int, bool) {
	row := DataRow(dfOutput)
	if row == "" {
		return 0, false
	}
	fields := strings.Fields(row)
	if len(fields) < 4 {
		return 0, false
	}
	return FreeGB(fields[3])
}

// Mounted reports whether an entry for path exists in a `/proc/mounts` or
// `mountpoint -q`-style input. Given the classical `mountpoint -q <path>`
// exit-code probe, this function instead inspects captured /proc/mounts text:
// it looks for a line whose mount point equals path. ok=false when absent.
func Mounted(procMounts, path string) bool {
	for _, line := range strings.Split(procMounts, "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[1] == path {
			return true
		}
	}
	return false
}

// ReadOnly reports whether a `/proc/mounts` line for path carries the `ro`
// mount option (md.sh:1169 `grep "$MOUNT_ROOT" /proc/mounts | grep -q " ro,"`).
// The match is the substring " ro," against the options field.
func ReadOnly(procMounts, path string) bool {
	for _, line := range strings.Split(procMounts, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 || fields[1] != path {
			continue
		}
		if strings.Contains(line, " ro,") {
			return true
		}
	}
	return false
}
