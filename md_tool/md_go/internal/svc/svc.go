// Package svc implements the md.sh service-control layer: the soc1/soc2
// target resolution, service lifecycle (start/stop/restart/status), service
// log streaming, the Recorder on/off path, the channel (dtop) launch, and the
// ~/.md_remotes remote-branch file operations.
//
// Semantic fidelity note: these functions mirror md.sh's svc::_resolve_soc_arg
// / svc::manage / svc::check / svc::log / svc::recorder / svc::channel and
// vmc::remote, including a few quirks that are documented rather than "fixed":
//
//   - Manage ALWAYS reports success (nil) even when the underlying systemctl
//     or ssh failed; the Bash version returns 0 unconditionally (md.sh:700)
//     and relies on the follow-up Check to surface the real state. This
//     package keeps that contract.
//   - Check on soc2 swallows a 255 (ssh transport failure) result — it returns
//     an error and emits no message, mirroring md.sh:650-658.
//   - Recorder's "off" continues even when the disk is not mounted (only "on"
//     is blocked), mirroring md.sh:771-774.
//
// Execution is abstracted behind a Shell so soc1 (local) and soc2 (ssh) share
// one code path and every branch is testable in-process via sshtest.
package svc

import (
	"context"
	"fmt"

	"mdrive/md/internal/config"
	"mdrive/md/internal/logx"
)

// ResolveSOCArg normalizes the user-supplied soc argument (md.sh
// svc::_resolve_soc_arg :705-716). It returns "soc1", "soc2" or "both"; an
// unusable value returns an error (the Bash version prints log_err to stderr
// and returns 1).
func ResolveSOCArg(arg string) (string, error) {
	switch arg {
	case "", "soc1", "1":
		if arg == "" {
			return "both", nil
		}
		return "soc1", nil
	case "soc2", "2":
		return "soc2", nil
	default:
		return "", fmt.Errorf("无效 SOC 参数: %s（仅支持 1/soc1/2/soc2，缺省=双端）", arg)
	}
}

// ExecOut is a Shell command's captured stdout/stderr/exit code.
type ExecOut struct {
	Stdout string
	Stderr string
	Code   int
}

// Chunk is one incremental slice of a Stream command's stdout or stderr.
type Chunk struct {
	Stream string // "stdout" | "stderr"
	Data   []byte
}

// Shell runs shell command strings against a target machine. soc1 commands run
// locally; soc2 commands run over ssh. The command string is executed under
// sh -c, which is exactly how the Bash tool hands a pipe/&&-joined string to
// the remote shell.
type Shell interface {
	// Exec runs one command and captures its output (non-interactive).
	Exec(ctx context.Context, command string) (ExecOut, error)
	// Stream runs one command and delivers its output incrementally.
	Stream(ctx context.Context, command string) (<-chan Chunk, <-chan error)
	// Interactive wires one command to the local terminal (TTY passthrough).
	Interactive(ctx context.Context, command string) error
	// Close releases any pooled transport.
	Close() error
}

// Svc is the service-control façade. It holds the config and the log; the
// shell factory decides whether a target is local (soc1) or remote (soc2).
type Svc struct {
	cfg   config.Config
	log   *logx.Logger
	shell func(soc string, ctx context.Context) (Shell, error)
}

// New builds a Svc. The shell factory maps "soc1" to a local Shell and
// "soc2" to a remote (ssh) Shell built from cfg.SOC2IP. A nil or
// non-"soc1"/"soc2" soc yields a NewLocal shell (the Bash tool's default
// implicit target).
func New(cfg config.Config, log *logx.Logger) *Svc {
	return &Svc{
		cfg: cfg,
		log: log,
		shell: func(soc string, ctx context.Context) (Shell, error) {
			if soc == "soc2" {
				return NewRemote(ctx, cfg)
			}
			return NewLocal(), nil
		},
	}
}

// NewWithShell builds a Svc with a custom shell factory (tests inject fakes
// here to avoid spawning real local/SSH transports).
func NewWithShell(cfg config.Config, log *logx.Logger, shell func(soc string, ctx context.Context) (Shell, error)) *Svc {
	return &Svc{cfg: cfg, log: log, shell: shell}
}

// Manage runs action on soc. Valid actions are start/stop/restart; anything
// else is rejected before any command runs (a whitelist — md.sh does not
// validate here because dispatch does, but Go must not let an arbitrary string
// reach `systemctl $action`).
//
// It always returns nil on a successful dispatch (see the package doc on the
// md.sh:700 quirk). Follow-up Check reports actual state.
func (s *Svc) Manage(ctx context.Context, action, soc string) error {
	switch action {
	case "start", "stop", "restart":
	default:
		return fmt.Errorf("无效动作: %s（仅支持 start/stop/restart）", action)
	}

	// "both" is not a Shell target, so iterate the two concrete socs.
	socs := []string{soc}
	if soc == "both" {
		socs = []string{"soc1", "soc2"}
	}
	for _, target := range socs {
		s.manageOne(ctx, action, target)
	}
	return nil
}

func (s *Svc) manageOne(ctx context.Context, action, soc string) {
	sh := s.shellOr(soc, ctx)
	if sh == nil {
		return
	}

	s.log.Info("%s %s mdrive service...", action, soc)
	if action == "stop" {
		s.log.Info("停止 mdrive 服务（数据盘 chown 耗时可能导致 30-60s 等待）...")
	}

	if soc == "soc2" {
		cmd := fmt.Sprintf("timeout 15 sudo systemctl %s mdrive.service", action)
		_, _ = sh.Exec(ctx, cmd)
	} else {
		cmd := "systemctl " + action + " mdrive.service"
		_, _ = sh.Exec(ctx, cmd)
	}

	if action == "stop" {
		s.pollStopped(ctx, sh, soc)
	}

	// Follow-up status report (md.sh vm::manage calls svc::check at the end).
	if got := s.Check(ctx, soc); got != nil {
		// check failure itself is already logged; nothing more to do here.
	}
}

// pollStopped waits up to ~12s for mdrive.service to leave the active state.
// It mirrors the T1.1 stop-verification logic: soc1 polls locally; soc2 polls
// over ssh and warns only when the ssh probe still reports active after the
// window (md.sh:691-697).
func (s *Svc) pollStopped(ctx context.Context, sh Shell, soc string) {
	if soc == "soc2" {
		// ssh returns 1 when the loop exits early (service stopped), 0 when it
		// ran the full window and the service is still active.
		probe := `for i in $(seq 1 12); do systemctl is-active --quiet mdrive.service || exit 1; sleep 1; done`
		if out, err := sh.Exec(ctx, probe); err == nil && out.Code == 0 {
			s.log.Warn("[soc2] mdrive.service 停止超时，可能仍在退出中（数据盘 chown 耗时较长），继续前请确认")
		}
		return
	}

	// soc1 local polling: break as soon as is-active returns non-zero.
	for i := 0; i < 12; i++ {
		if out, _ := sh.Exec(ctx, "systemctl is-active --quiet mdrive.service"); out.Code != 0 {
			return // stopped
		}
		sleepCtx(ctx) // 1s per tick
	}
	// Ran the full window without confirming a stop.
	s.log.Warn("[soc1] mdrive.service 停止超时，可能仍在退出中（数据盘 chown 耗时较长），继续前请确认")
}

// Check reports the service state for soc (md.sh svc::check :641-660). soc2's
// ssh transport failure (255) returns an error and emits nothing.
func (s *Svc) Check(ctx context.Context, soc string) error {
	sh := s.shellOr(soc, ctx)
	if sh == nil {
		return nil
	}

	// "both" resolves into two concrete reports.
	if soc == "both" {
		_ = s.Check(ctx, "soc1")
		return s.Check(ctx, "soc2")
	}

	// is-active --quiet needs no sudo on either side.
	out, err := sh.Exec(ctx, "systemctl is-active --quiet mdrive.service")
	if err != nil {
		// soc2 255: silent + error (md.sh:654-657).
		s.log.Warn("[%s] 连接失败，无法查询服务状态", soc)
		return err
	}
	if soc == "soc2" && out.Code == 255 {
		// ssh-level failure surfaces as ErrConnFailed; md.sh treats 255 as
		// "silent, return 1". We already logged a hint; return the error.
		return fmt.Errorf("[soc2] ssh 无法连到远端")
	}

	state := "Running"
	if out.Code != 0 {
		state = "Stopped or Failed"
	}
	s.log.Info("[%s]服务状态: %s", soc, state)
	return nil
}

// Recorder controls the soc2 Recorder (md.sh svc::recorder :736-782). action
// defaults to "on". Only soc2 is targeted.
func (s *Svc) Recorder(ctx context.Context, action string) error {
	if action == "" {
		action = "on"
	}
	var supervisorAction, text string
	switch action {
	case "on":
		supervisorAction, text = "start", "启动"
	case "off":
		supervisorAction, text = "stop", "停止"
	default:
		return fmt.Errorf("用法: md record [on|off]")
	}

	sh := s.shellOr("soc2", ctx)
	if sh == nil {
		return fmt.Errorf("无法建立 soc2 连接")
	}

	// Disk pre-check (md.sh:755-769), always run.
	diskReady := s.checkRecorderDisk(ctx, sh)

	if action == "on" && !diskReady {
		s.log.Err("拒绝启动 Recorder，请先修复 soc2 数据盘挂载")
		return fmt.Errorf("soc2 数据盘未挂载")
	}

	cmd := fmt.Sprintf("sudo supervisorctl %s Recorder 2>/dev/null", supervisorAction)
	if out, err := sh.Exec(ctx, cmd); err != nil || out.Code != 0 {
		if err != nil {
			s.log.Err("soc2 Recorder %s失败", text)
			return err
		}
		s.log.Err("soc2 Recorder %s失败", text)
		return fmt.Errorf("supervisorctl %s Recorder 退出码 %d", supervisorAction, out.Code)
	}
	s.log.Ok("soc2 Recorder 已%s", text)
	return nil
}

// checkRecorderDisk probes the soc2 data disk and warns on any abnormal state.
// It returns true when the disk is mounted (md.sh:755-769). The "off" path
// proceeds regardless of the returned bool.
func (s *Svc) checkRecorderDisk(ctx context.Context, sh Shell) bool {
	out, err := sh.Exec(ctx, fmt.Sprintf("timeout 2 mountpoint -q %s", s.cfg.MountRoot))
	if err != nil || out.Code != 0 {
		s.log.Err("soc2 硬盘未挂载或无法访问: %s", s.cfg.MountRoot)
		s.log.Err("提示: 运行 md check，按提示修复硬盘后再 md record on")
		return false
	}
	s.log.Info("[soc2]硬盘: 已挂载")

	avail := s.remoteDiskFreeGB(ctx, sh)
	if avail < 0 {
		s.log.Warn("无法读取 soc2 数据盘剩余空间: %s", s.cfg.MountRoot)
	} else if avail < 200 {
		s.log.Warn("soc2 数据盘剩余空间不足 200GB (当前: %dGB)！", avail)
	}
	return true
}

// remoteDiskFreeGB returns the available GB on the soc2 data disk, or -1 when
// it cannot be determined (md.sh:758-760: `df -BG ... | awk 'NR==2 {print
// $4}' | tr -d 'G'`).
func (s *Svc) remoteDiskFreeGB(ctx context.Context, sh Shell) int {
	cmd := fmt.Sprintf("df -BG %s 2>/dev/null | awk 'NR==2 {print \\$4}' | tr -d 'G'", s.cfg.MountRoot)
	out, err := sh.Exec(ctx, cmd)
	if err != nil || out.Code != 0 {
		return -1
	}
	var gb int
	if _, err := fmt.Sscanf(out.Stdout, "%d", &gb); err != nil {
		return -1
	}
	return gb
}

// Channel launches dtop — on soc1 locally, on soc2 over ssh with the
// environment prefix (md.sh svc::channel :785-798).
func (s *Svc) Channel(ctx context.Context, soc string) error {
	if soc == "" || soc == "soc1" || soc == "1" {
		sh := s.shellOr("soc1", ctx)
		if sh == nil {
			return fmt.Errorf("无法启动本地 dtop")
		}
		return sh.Interactive(ctx, "dtop")
	}
	if soc == "soc2" || soc == "2" {
		sh := s.shellOr("soc2", ctx)
		if sh == nil {
			return fmt.Errorf("无法建立 soc2 连接")
		}
		return sh.Interactive(ctx, interactiveSoc2())
	}
	return fmt.Errorf("无效 SOC 参数: %s（仅支持 1/soc1/2/soc2，缺省=soc1）", soc)
}

// shellOr returns the Shell for a soc, or nil when the factory failed. The
// caller must nil-check.
func (s *Svc) shellOr(soc string, ctx context.Context) Shell {
	sh, err := s.shell(soc, ctx)
	if err != nil {
		s.log.Err("[%s] 无法建立连接: %v", soc, err)
		return nil
	}
	return sh
}

// interactiveSoc2 renders the env + source + dtop prefix md.sh:soc2:791.
// GLOG_log_dir and VMC_SOFTWARE are expanded locally (see sshx
// InteractiveRequest semantics); the dtop command is the Shell's Interactive
// input, so this helper just returns the command string without quoting.
func interactiveSoc2() string {
	return "export MDRIVE_ROOT_DIR=/mdrive && export MDRIVE_DEP_DIR=/mdrive/mdrive_dep " +
		"&& source $VMC_SOFTWARE/mdrive/setup.sh " +
		"&& export GLOG_log_dir=${GLOG_log_dir:-/mnt/ufs_data/project/data/log} && dtop"
}
