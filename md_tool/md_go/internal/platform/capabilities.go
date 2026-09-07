package platform

import (
	"context"
	"strings"
)

// Capabilities describes what a target platform actually has, so an svc命令
// can give a targeted error ("this environment has no systemd") instead of a
// bare "command not found" in a container or a bare soc (P2/req4).
type Capabilities struct {
	HasSystemD    bool
	HasSupervisor bool
	HasDataMount  bool
	HasChannel    bool // dtop or cyber_monitor present
}

// MustCapabilities runs the capability probes (via the injectable runner) and
// returns the set. A probe that cannot run (the command is absent) simply
// marks the capability off — the runner returning an error is treated as "not
// present" rather than a hard failure.
func MustCapabilities(ctx context.Context, run runFunc) Capabilities {
	return Capabilities{
		HasSystemD:    probePresent(ctx, run, "systemctl"),
		HasSupervisor: probePresent(ctx, run, "supervisorctl"),
		HasDataMount:  probePresent(ctx, run, "mountpoint") && probeHasDataMount(ctx, run),
		HasChannel:    probePresent(ctx, run, "dtop") || probePresent(ctx, run, "cyber_monitor"),
	}
}

// probePresent reports whether a command is on the target's PATH by running
// `command -v <cmd>`.
func probePresent(ctx context.Context, run runFunc, cmd string) bool {
	if run == nil {
		return false
	}
	out, err := run(ctx, "sh", "-c", "command -v "+cmd+" >/dev/null 2>&1")
	if err != nil {
		return false
	}
	return strings.TrimSpace(out) != ""
}

// probeHasDataMount checks the canonical data mount point exists (via an
// explicit mountpoint probe). Kept separate so a soc without the data disk
// mounted still reports "no data mount" distinctly from "no mountpoint tool".
func probeHasDataMount(ctx context.Context, run runFunc) bool {
	if run == nil {
		return false
	}
	out, err := run(ctx, "mountpoint", "-q", "/media/data")
	if err != nil {
		return false
	}
	return strings.TrimSpace(out) == "" && err == nil
}
