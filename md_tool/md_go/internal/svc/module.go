package svc

import (
	"context"
	"fmt"
	"regexp"
	"strings"
)

// ModuleRow is one module's status line as surfaced by `md m`. It mirrors the
// `[socN] mod STATE tail` rows that md.sh fetch_combined (md.sh:966-986)
// produces from `sudo supervisorctl status` on both socs.
type ModuleRow struct {
	SOC   string
	Name  string
	State string
	Tail  string
}

// StatusClass classifies a row for color rendering, mirroring fetch_combined's
// YELLOW (RUNNING with uptime starting 0:00:0) / GREEN (RUNNING) / RED
// (anything else) scheme.
type StatusClass int

const (
	StatusRunning StatusClass = iota
	StatusStarting
	StatusStopped
)

// ansiRe matches ANSI escape sequences (`\033[...m`) so selected fzf rows can
// be parsed free of color codes (md.sh svc::mod_handler uses
// `sed 's/\x1b\[[0-9;]*m//g'`).
var ansiRe = regexp.MustCompile(`\x1b\[[0-9;]*m`)

// ParseSupervisorStatus parses the raw `supervisorctl status` output for one
// soc into ModuleRow values. soc is "soc1" or "soc2" and is prefixed to every
// row. The output's whitespace is squeezed the same way md.sh does
// (`tr -s ' '`), so each line yields (name, state, tail...).
//
// Example input line: `Camera    RUNNING   pid 1234, uptime 0:00:05`
func ParseSupervisorStatus(soc, output string) []ModuleRow {
	var rows []ModuleRow
	for _, line := range strings.Split(output, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		rows = append(rows, ModuleRow{
			SOC:   soc,
			Name:  fields[0],
			State: fields[1],
			Tail:  strings.Join(fields[2:], " "),
		})
	}
	return rows
}

// Class returns the status class for a row (md.sh:976-983). The "starting"
// probe is a substring grep (`grep -q "uptime 0:00:0"`), not a prefix — the
// tail starts with `pid N, uptime ...`.
func (r ModuleRow) Class() StatusClass {
	switch {
	case r.State == "RUNNING" && strings.Contains(r.Tail, "uptime 0:00:0"):
		return StatusStarting
	case r.State == "RUNNING":
		return StatusRunning
	default:
		return StatusStopped
	}
}

// Render returns the display line with ANSI colors matching fetch_combined's
// `[%-4s] %-45s %-8s %s` printf (md.sh:978-983). The color is applied by class
// and the whole row is wrapped with the reset (nc) at the end.
func (r ModuleRow) Render(nc string) string {
	color := yellow
	switch r.Class() {
	case StatusRunning:
		color = green
	case StatusStopped:
		color = red
	}
	body := fmt.Sprintf("[%-4s] %-45s %-8s %s", r.SOC, r.Name, r.State, r.Tail)
	return color + body + nc
}

// StripANSI removes ANSI escapes from a selected fzf row (md.sh:892).
func StripANSI(s string) string {
	return ansiRe.ReplaceAllString(s, "")
}

// module colors (mirror md.sh's \033[1;3Xm).
const (
	red    = "\033[1;31m"
	green  = "\033[1;32m"
	yellow = "\033[1;33m"
)

// FetchModules returns the combined module status for both socs (md.sh
// fetch_combined:966-986). Each soc's `sudo supervisorctl status` is gathered
// and prefixed with its soc name. A transport failure on a soc is skipped; the
// function errors only when neither soc yielded a usable listing.
func (s *Svc) FetchModules(ctx context.Context) ([]ModuleRow, error) {
	var rows []ModuleRow
	for _, soc := range []string{"soc1", "soc2"} {
		sh := s.shellOr(soc, ctx)
		if sh == nil {
			continue
		}
		out, err := sh.Exec(ctx, "sudo supervisorctl status 2>/dev/null")
		sh.Close()
		if err != nil {
			continue
		}
		rows = append(rows, ParseSupervisorStatus(soc, out.Stdout)...)
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("无法获取模块状态（soc1/soc2 均不可达）")
	}
	return rows, nil
}
