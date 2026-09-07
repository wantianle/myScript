// Package platform centralises the "which machine am I and how do I reach the
// other soc" logic that md.sh scatters across the tool. It answers the two
// questions the dual-soc routing (P2) needs:
//
//   - Identity: is the current host soc1, soc2, or neither (a PC / x86
//     container / CI)? It uses the same signal mdrive4's startup_orin.sh uses —
//     the IPv4 addresses bound to the mgbe3_0 interface (see platform_test.go
//     for the exact membership and the rationale from startup_orin.sh :85-128).
//   - Topology: given the current host, resolve a logical soc target into a
//     concrete execution endpoint (local or over ssh to a specific host).
//
// The package keeps identity detection injectable (a command runner) so it is
// unit-testable without spawning `ip`, matching how svc tests inject a fake
// Shell.
package platform

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"mdrive/md/internal/config"
)

// Identity is the logical identity of the current host. It mirrors the
// config.SOCID type but stays independent so平台 can be used without importing
// config where unnecessary (kept as an alias for clarity).
type Identity = config.SOCID

// soc membership sets, derived from startup_orin.sh :85-128. Either scheme's
// address being present on mgbe3_0 marks the host as that soc.
var soc1Addrs = []string{"172.168.16.101", "192.168.1.100"}
var soc2Addrs = []string{"172.168.16.103", "192.168.1.101"}

// runFunc runs a command and returns its stdout. It is injectable so identity
// detection is testable without spawning `ip`.
type runFunc func(ctx context.Context, args ...string) (string, error)

// defaultRun invokes a command and returns stdout (stdout only — stderr is
// discarded for identity probes, matching the on-call grep semantics).
var defaultRun runFunc = func(ctx context.Context, args ...string) (string, error) {
	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("%s: %w (%s)", args[0], err, strings.TrimSpace(stderr.String()))
	}
	return stdout.String(), nil
}

// DetectIdentity returns the current host's logical identity. An explicit
// cfg.SOCID wins (env override MDRIVE_SOC_ID); otherwise it probes mgbe3_0 via
// run and classifies by address membership. Any probe error or non-matching
// address yields config.SOCExternal.
func DetectIdentity(ctx context.Context, cfg config.Config) Identity {
	if cfg.SOCID == config.SOC1 || cfg.SOCID == config.SOC2 {
		return cfg.SOCID
	}
	return detectByAddress(ctx, cfg, defaultRun)
}

// detectByAddress probes the mgbe3_0 interface and classifies the host. It is
// separated from DetectIdentity so the address logic is testable with an
// injected runner.
func detectByAddress(ctx context.Context, cfg config.Config, run runFunc) Identity {
	out, err := run(ctx, "ip", "-4", "addr", "show", "mgbe3_0")
	if err != nil {
		return config.SOCExternal
	}
	if containsAny(out, soc1Addrs) {
		return config.SOC1
	}
	if containsAny(out, soc2Addrs) {
		return config.SOC2
	}
	return config.SOCExternal
}

func containsAny(haystack string, needles []string) bool {
	for _, n := range needles {
		if strings.Contains(haystack, n) {
			return true
		}
	}
	return false
}

// IsContainer reports whether the current host is running inside a container
// (the x86 dev/sim environment). The signal is a /.dockerenv marker plus an
// amd64 arch (the vehicle socs are arm64; an amd64 host without the marker is a
// dev/CI PC, which is different). This is the req4 "slim tool" boundary: in a
// container md only manages the local supervisor — it does not ssh to socs and
// does not run vmc OTA (install/upgrade/rollback).
func IsContainer() bool {
	if _, err := os.Stat("/.dockerenv"); err != nil {
		return false
	}
	return runtime.GOARCH == "amd64"
}
