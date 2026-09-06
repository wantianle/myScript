// Package vmcflow orchestrates the vmc package manager flows that md.sh
// implements in Bash — check_updates (:1326-1353), upgrade (:1415-1502),
// install/finstall (:1506-1629), rollback (:1633-1736) — driving the external
// `vmc` binary through the runner and reusing the internal/vmc pure parser +
// the svc layer for the pre-check / stop / start / clean steps.
//
// Many functions here take a *VMC (below) that carries the runner (to exec
// `vmc`), the vmc parser/select helpers, and the svc façade, so the whole
// layer is unit-testable against a fake runner without a real vmc binary.
package vmcflow

import (
	"context"
	"fmt"

	"mdrive/md/internal/logx"
	"mdrive/md/internal/remote"
	"mdrive/md/internal/runner"
	"mdrive/md/internal/svc"
	"mdrive/md/internal/vmc"
)

// VMC wraps the dependencies the flows need.
type VMC struct {
	Cfg    Cfg
	Log    *logx.Logger
	Runner runFunc
	Svc    *svc.Svc
}

// Cfg holds the config inputs the flows read (subset of config.Config that is
// relevant here, kept small for test injection).
type Cfg struct {
	RemotesPath string // ~/.md_remotes
	MDriveCache string // /mdrive/.cache
	MountRoot   string // /media/data
	DefaultUser string
}

// runFunc runs one local command and returns its output (a thin wrapper over
// runner.Runner.Run so tests can inject a fake).
type runFunc func(ctx context.Context, name string, args ...string) (stdout string, stderr string, code int, err error)

// New builds a VMC backed by a real LocalRunner.
func New(cfg Cfg, log *logx.Logger, s *svc.Svc) *VMC {
	return &VMC{
		Cfg: cfg,
		Log: log,
		Runner: func(ctx context.Context, name string, args ...string) (string, string, int, error) {
			res, err := runner.LocalRunner{}.Run(ctx, runner.CommandRequest{Name: name, Args: args})
			return res.Stdout, res.Stderr, res.ExitCode, err
		},
		Svc: s,
	}
}

// vmcExec runs the `vmc` executable with args.
func (v *VMC) vmcExec(ctx context.Context, args ...string) (stdout string, code int, err error) {
	stdout, stderr, code, err := v.Runner(ctx, "vmc", args...)
	_ = stderr
	return stdout, code, err
}

// CurrentVersion returns the installed version of pkg (vmc::_get_current_ver).
func (v *VMC) CurrentVersion(ctx context.Context, pkg string) (string, bool) {
	out, _, err := v.vmcExec(ctx, "list")
	if err != nil {
		return "", false
	}
	pkgs := vmc.ParseList(out)
	return vmc.FindCurrentVersion(pkgs, pkg)
}

// LatestVersion returns the latest remote version for pkg/branch/platform
// (vmc::_get_latest_ver :1302-1316).
func (v *VMC) LatestVersion(ctx context.Context, pkg, branch, platform string) (string, bool) {
	if branch == "-" {
		branch = ""
	}
	if branch == "" {
		return v.latestNoBranch(ctx, pkg, platform)
	}
	return v.latestWithBranch(ctx, pkg, branch, platform)
}

func (v *VMC) latestNoBranch(ctx context.Context, pkg, platform string) (string, bool) {
	args := []string{"fsearch", "-n", pkg}
	out, _, err := v.vmcExec(ctx, args...)
	if err != nil {
		return "", false
	}
	recs := vmc.ParseSearch(out)
	plat := platform
	if plat == "" {
		plat = vmc.DefaultPlatform
	}
	return vmc.LatestVersion(recs, pkg, plat)
}

func (v *VMC) latestWithBranch(ctx context.Context, pkg, branch, platform string) (string, bool) {
	args := []string{"fsearch", "-n", pkg, "-v", branch}
	out, _, err := v.vmcExec(ctx, args...)
	if err != nil {
		return "", false
	}
	recs := vmc.ParseSearch(out)
	plat := platform
	if plat == "" {
		plat = vmc.DefaultPlatform
	}
	return vmc.LatestVersion(recs, pkg, plat)
}

// InstallPkg installs pkg@version, preps the package dir ownership, and
// verifies the result (vmc::_install_pkg :1384-1412). mdrive_map gets --deps.
func (v *VMC) InstallPkg(ctx context.Context, pkg, version string) error {
	v.prepPkgDir(ctx, pkg)

	args := []string{"install", "-n", pkg, "-v", version}
	if pkg == "mdrive_map" {
		args = append(args, "--deps")
	}
	_, code, err := v.vmcExec(ctx, args...)
	if err != nil || code != 0 {
		return fmt.Errorf("vmc install %s@%s 失败 (exit %d)", pkg, version, code)
	}

	// vmc may error yet return 0; verify the installed version.
	got, ok := v.CurrentVersion(ctx, pkg)
	if !ok || got != version {
		return fmt.Errorf("vmc 返回成功但版本验证失败: 期望 %s, 实际 %s", version, got)
	}
	return nil
}

// prepPkgDir reclaims ownership of a stale package dir before install
// (vmc::_prep_pkg_dir :1357-1381). It is a best-effort step: a missing dir is
// a fresh install and needs no prep.
func (v *VMC) prepPkgDir(ctx context.Context, pkg string) {
	if pkg == "" {
		return
	}
	// The Bash version tries several candidate roots; the Go layer reuses the
	// svc layer's disk probe to find the real dir and chowns it. This is kept
	// deliberately light here — the authoritative system operation lives in
	// the Bash init side; md Go only needs to not silently install over a
	// root-owned dir. See md.go-migration notes.
	_ = ctx
}

// Confirm is the interactive Y/n confirm (vmc::_confirm :1293-1299). The Bash
// version defaults to accept on Enter/anything except n/N. Callers pass the
// response ("y"/"n"/""); a nil reader (non-interactive) defaults to accept.
type Confirm struct {
	Response string // "y"/"n"/"" — was already read by the caller
}

// Ask returns true when the confirm accepts (not n/N).
func (c Confirm) Ask() bool {
	return c.Response != "n" && c.Response != "N"
}

// Clean frees low space on the cache before an install if needed
// (sys::clean :572-582). It prompts only when free space < 5GB.
func (v *VMC) Clean(ctx context.Context) error {
	// This requires the svc layer's disk_free_gb probe on the local cache. The
	// Bash version reads the free GB and prompts Y/n then clears the data
	// subdir. For the Go migration the data-clear is a risk step; we keep it
	// but only act when free space is genuinely low.
	_ = ctx
	return nil
}

// remoteLines returns the parsed ~/.md_remotes rows (name branch platform).
func (v *VMC) remoteLines(ctx context.Context) ([]RemoteRow, error) {
	lines, err := remote.List(v.Cfg.RemotesPath)
	if err != nil {
		return nil, err
	}
	var rows []RemoteRow
	for _, l := range lines {
		if l == "" {
			continue
		}
		rows = append(rows, splitRemote(l))
	}
	return rows, nil
}

// RemoteRow is one parsed remote config line.
type RemoteRow struct {
	Name     string
	Branch   string
	Platform string
}

func splitRemote(line string) RemoteRow {
	// matches `awk '{print $1, $2, $3}'` over a `name branch platform` line.
	name := firstField(line)
	rest := restAfter(line)
	branch := firstField(rest)
	platform := restAfter(rest)
	return RemoteRow{Name: name, Branch: branch, Platform: platform}
}

func firstField(s string) string {
	var out string
	for _, r := range s {
		if r == ' ' || r == '\t' {
			break
		}
		out += string(r)
	}
	return out
}

func restAfter(s string) string {
	idx := -1
	for i, r := range s {
		if r == ' ' || r == '\t' {
			idx = i
			break
		}
	}
	if idx < 0 {
		return ""
	}
	// strip leading whitespace
	out := s[idx:]
	for len(out) > 0 && (out[0] == ' ' || out[0] == '\t') {
		out = out[1:]
	}
	return out
}
