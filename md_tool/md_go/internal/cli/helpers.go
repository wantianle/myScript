package cli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"mdrive/md/internal/remote"

	"github.com/spf13/cobra"
)

// osStderr returns the standard error writer (used for streamed command
// output that should not be buffered).
func osStderr() io.Writer { return os.Stderr }

// errBadSOC returns the invalid-soc error text md.sh emits.
func errBadSOC(arg string) error {
	return fmt.Errorf("无效 SOC 参数: %s（仅支持 1/soc1/2/soc2，缺省=soc1）", arg)
}

// cmdUsage prints the extended usage to stderr and returns a sentinel error so
// the command exits non-zero.
func cmdUsage(sub string) error {
	switch sub {
	case "remote":
		fmt.Fprintln(os.Stderr, "用法: md remote list")
		fmt.Fprintln(os.Stderr, "       md remote add <name> <branch> [platform]")
		fmt.Fprintln(os.Stderr, "       md remote del <name>")
	}
	return fmt.Errorf("用法有误: md %s", sub)
}

// remotePath resolves the configuration file path (~/.md_remotes).
func remotePath() string {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return remote.DefaultFile
	}
	return filepath.Join(home, ".md_remotes")
}

// argOr returns args[i] when present, otherwise fallback.
func argOr(args []string, i int, fallback string) string {
	if i < len(args) {
		return args[i]
	}
	return fallback
}

// stdoutP writes to stdout.
func stdoutP(s string) (int, error) { return fmt.Fprint(os.Stdout, s) }

// flagYes reports whether the global --yes flag is set. It is a persistent
// flag on the root command, so a subcommand reads it through its inherited
// (merged) flag set.
func flagYes(cmd *cobra.Command) bool {
	if cmd == nil {
		return false
	}
	v, err := cmd.Flags().GetBool("yes")
	if err != nil {
		return false
	}
	return v
}

// flagJSON reports whether the global --json flag is set (machine-readable
// output). Persistent, so read via the subcommand's merged flag set.
func flagJSON(cmd *cobra.Command) bool {
	if cmd == nil {
		return false
	}
	v, err := cmd.Flags().GetBool("json")
	if err != nil {
		return false
	}
	return v
}

// writeJSON marshals v to stdout as indented JSON (P4 --json output). Errors are
// returned so the caller can exit non-zero.
func writeJSON(v any) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// stdoutfd returns the stdout file descriptor for terminal checking.
func stdoutfd() uintptr { return os.Stdout.Fd() }

// isTerminal reports whether stdout is attached to a character device (a real
// terminal). A non-TTY stdout means the caller is piping/redirecting, so a
// full-screen TUI must degrade to plain text output rather than emit escape
// sequences (P1 non-TTY guard).
func isTerminal(fd uintptr) bool {
	fi, err := os.Stdout.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0 && fi.Mode()&os.ModeNamedPipe == 0
}

// readAllStdin reads everything from stdin into a string (the `md install`
// version-lines input).
func readAllStdin() (string, error) {
	b, err := io.ReadAll(os.Stdin)
	return string(b), err
}

// readLineStdin reads one line from stdin, returning it trimmed. It blocks only
// until the next newline (not until EOF/Ctrl-D like io.ReadAll would), so an
// interactive confirm prompt returns as soon as the operator presses Enter.
// Empty lines (bare Enter) and whitespace-only input both yield "".
func readLineStdin() string {
	r := bufio.NewReader(os.Stdin)
	line, _ := r.ReadString('\n')
	return strings.TrimSpace(line)
}
