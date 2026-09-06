package sshx

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// InteractiveRequest describes an interactive remote session. The terminal
// stdin/stdout/stderr are connected straight through, exactly like md.sh's
// `ssh ${SSH_OPTS[@]} -t user@host "export ... && source ... && cmd"` calls
// (md.sh:183, md.sh:490, md.sh:725, md.sh:791) — the `-t` scenario needs the
// system ssh binary because it requires a real pty, terminal control and
// password prompts that the pure Go client cannot provide.
type InteractiveRequest struct {
	Shell string // 完整远端命令行（可含 export/source 前缀或单独命令）
	// ForceNoTTY adds `-T` (default false). Every md.sh interactive call
	// passes -t unconditionally, so the zero value requests a pty; set
	// ForceNoTTY true only when the remote command must run without a
	// terminal (e.g. from CI, where no tty is attached).
	ForceNoTTY bool
	Env        []string // "K=V" 元素，会渲染为 `export K=V` 前缀并排在 Shell 之前
	Source     []string // 需 source 的脚本路径，渲染为 `source <path>`，排在 export 之后
}

// Interactive runs a full-screen interactive session via the system `ssh`
// binary with the md.sh SSH_OPTS-derived flags plus -t (unless ForceNoTTY is
// set). The remote command is passed as a single argv element so the remote
// shell receives it verbatim (no local re-quoting hazards).
//
// The remote exit code is returned as *ExitError for codes other than 255; an
// ssh exit code of 255 means ssh itself could not establish or keep the
// session and is classified as ErrConnFailed (OpenSSH convention).
func (c *Client) Interactive(ctx context.Context, req InteractiveRequest) error {
	c.opMu.Lock()
	defer c.opMu.Unlock()

	cfg := c.cfg
	if _, err := loadSigner(cfg.KeyPath); err != nil {
		return err // fail with a precise ErrAuthFailed before exec'ing ssh
	}
	remote := buildRemoteCommand(req)
	args := interactiveSSHArgs(cfg, req, remote)

	cmd := exec.CommandContext(ctx, "ssh", args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	err := cmd.Run()
	if err == nil {
		return nil
	}
	if ctx.Err() != nil {
		return fmt.Errorf("%w: %v", ctx.Err(), err)
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		code := exitErr.ExitCode()
		if code != 255 {
			return &ExitError{Code: code}
		}
		return fmt.Errorf("%w: ssh exited with %d", ErrConnFailed, code)
	}
	return fmt.Errorf("%w: %v", ErrConnFailed, err)
}

// buildRemoteCommand renders Env / Source / Shell into one remote command
// string, mirroring md.sh's `export A=... && export B=... && source ... && cmd`
// composition in svc::channel (md.sh:791).
//
// Env values are expanded LOCALLY with os.ExpandEnv before quoting, matching
// the double-quoted md.sh string in which the local bash expands `${...}`
// before the value goes over the wire. The expanded value is then passed to
// shellQuote, so the remote shell receives one literal word and never
// re-expands it. (os.ExpandEnv does not implement bash's `${VAR:-default}`
// syntax: such a value is expanded to the local value of the whole literal
// variable name, i.e. usually empty.)
func buildRemoteCommand(req InteractiveRequest) string {
	var parts []string
	for _, kv := range req.Env {
		parts = append(parts, "export "+renderEnv(kv))
	}
	for _, path := range req.Source {
		parts = append(parts, "source "+shellQuote(path))
	}
	if req.Shell != "" {
		parts = append(parts, req.Shell)
	}
	return strings.Join(parts, " && ")
}

// renderEnv renders one "K=V" entry. The value is first expanded locally with
// os.ExpandEnv (the local-bash equivalent of the double-quoted md.sh string)
// and then always single-quoted: the remote shell receives a literal value
// and performs no expansion of its own.
func renderEnv(kv string) string {
	idx := strings.IndexByte(kv, '=')
	if idx < 0 {
		return shellQuote(kv)
	}
	return shellQuote(kv[:idx]) + "=" + shellQuote(os.ExpandEnv(kv[idx+1:]))
}

// shellQuote returns s verbatim when it is a safe single shell word, and a
// single-quoted form otherwise. Embedded single quotes are escaped the
// standard shell way: close the quote, emit a literal quote, reopen.
func shellQuote(s string) string {
	if s != "" && allSafe(s) {
		return s
	}
	if !strings.ContainsRune(s, '\'') {
		return "'" + s + "'"
	}
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

// allSafe reports whether s contains only characters that are inert inside a
// shell word: no spaces, no glob metacharacters, no quotes, no operators.
// `$` and `${...}` are included because Env values are locally expanded
// (os.ExpandEnv) before this runs; the rare literal `$` that survives local
// expansion is treated as an ordinary character, matching how md.sh command
// strings themselves may contain `$`.
func allSafe(s string) bool {
	for i := 0; i < len(s); i++ {
		switch c := s[i]; {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9':
		case strings.ContainsRune("_./:=,+-${}", rune(c)):
		default:
			return false
		}
	}
	return true
}

// interactiveSSHArgs builds the system ssh argv. The remote command is the
// LAST element and always a single argv element, so the remote shell parses
// it without local shell interference.
func interactiveSSHArgs(cfg ClientConfig, req InteractiveRequest, remote string) []string {
	args := []string{
		"-o", "ConnectTimeout=" + fmtDuration(cfg.DialTimeout),
		"-o", "ServerAliveInterval=" + fmtDuration(cfg.KeepAliveInterval),
		"-o", "ServerAliveCountMax=" + strconv.Itoa(cfg.KeepAliveCountMax),
		"-o", "StrictHostKeyChecking=no",
		"-o", "UserKnownHostsFile=/dev/null",
		"-o", "LogLevel=ERROR",
	}
	if req.ForceNoTTY {
		args = append(args, "-T")
	} else {
		args = append(args, "-t")
	}
	if cfg.Port > 0 && cfg.Port != 22 {
		args = append(args, "-p", strconv.Itoa(cfg.Port))
	}
	args = append(args, "-i", cfg.KeyPath)
	args = append(args, cfg.User+"@"+cfg.Host)
	args = append(args, remote)
	return args
}

// fmtDuration renders a time.Duration as OpenSSH's integer seconds
// (ConnectTimeout=2 etc.). Sub-second values round up so the option is never
// 0, which OpenSSH would interpret as "no timeout".
func fmtDuration(d time.Duration) string {
	if d <= 0 {
		return "0"
	}
	secs := (int64(d) + 999_999_999) / 1_000_000_000 // ns → seconds, ceil
	return strconv.FormatInt(secs, 10)
}
