package cli

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"mdrive/md/internal/remote"
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

// readAllStdin reads everything from stdin into a string (the `md install`
// version-lines input).
func readAllStdin() (string, error) {
	b, err := io.ReadAll(os.Stdin)
	return string(b), err
}

// readLineStdin reads one trimmed line from stdin (a confirm response).
func readLineStdin() string {
	b, _ := io.ReadAll(os.Stdin)
	return strings.TrimSpace(string(b))
}
