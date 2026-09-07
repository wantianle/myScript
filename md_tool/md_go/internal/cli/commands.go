package cli

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	"mdrive/md/internal/config"
	"mdrive/md/internal/logx"
	"mdrive/md/internal/platform"
	"mdrive/md/internal/remote"
	"mdrive/md/internal/svc"
	"mdrive/md/internal/tui"
	"mdrive/md/internal/vmcflow"

	"github.com/spf13/cobra"
)

// newServiceRoot builds the md root command with the G3 service-control
// subcommands wired to the svc layer. The no-arg TUI (md m module menu) is
// wired separately in G4. Every RunE reads cmd.Context() so the signal-aware
// context main.go installs (SIGINT/SIGTERM) is honoured — this is what lets
// `md log 2` stop on Ctrl-C.
func newServiceRoot(cfg config.Config, programName, version string) *cobra.Command {
	log := logx.New()
	s := svc.New(cfg, log)
	vf := vmcflow.New(vmcflow.Cfg{
		RemotesPath:    remotePath(),
		MDriveCache:    cfg.MDriveCache,
		MountRoot:      cfg.MountRoot,
		MDriveDataRoot: cfg.MDriveDataRoot,
		DefaultUser:    defaultUser(cfg),
	}, log, s)

	root := &cobra.Command{
		Use:           programName,
		Short:         "MDrive vehicle operations tool",
		Version:       version,
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	// Global flags for scripted use (P1 pipe streaming). --quiet suppresses
	// non-error log lines so `md check --quiet` or `md status --quiet` leaves a
	// stable stderr of only ERRORs next to the stdout payload. --yes skips an
	// interactive confirm on upgrade/install/rollback (scripted, non-TTY use).
	var quiet, yes, jsonOut bool
	root.PersistentFlags().BoolVar(&quiet, "quiet", false, "suppress non-error log output (INFO/WARN)")
	root.PersistentFlags().BoolVar(&yes, "yes", false, "assume yes for confirm prompts (upgrade/install/rollback where available)")
	root.PersistentFlags().BoolVar(&jsonOut, "json", false, "emit machine-readable JSON instead of human text")
	root.PersistentPreRun = func(cmd *cobra.Command, args []string) {
		if quiet {
			log.SetQuiet(true)
		}
	}

	root.AddCommand(
		manageCmd(s, "start"),
		manageCmd(s, "stop"),
		manageCmd(s, "restart"),
		channelCmd(s),
		recordCmd(s),
		remoteCmd(),
		checkCmd(s),
		moduleCmd(s),
		exportCmd(cfg, log),
	)

	// Commands whose authority is host systemd/journald (status/log) or the vmc
	// OTA channel (install/upgrade/rollback) are only meaningful on a vehicle
	// soc. In a container (req4 slim tool) there is no systemd-as-PID1 and no
	// journald, and no OTA install use, so these are not registered — the
	// container keeps only the supervisor/service management surface.
	if !platform.IsContainer() {
		root.AddCommand(
			statusCmd(s),
			logCmd(s),
			upgradeCmd(vf, s),
			installCmd(vf, s),
			rollbackCmd(vf),
		)
	}

	return root
}

// socArg parses an optional soc argument (default both) via svc.ResolveSOCArg.
func socArg(args []string) (string, error) {
	arg := ""
	if len(args) > 0 {
		arg = args[0]
	}
	return svc.ResolveSOCArg(arg)
}

func manageCmd(s *svc.Svc, action string) *cobra.Command {
	return &cobra.Command{
		Use:   action + " [1|2]",
		Short: action + " mdrive service (default both socs)",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			soc, err := socArg(args)
			if err != nil {
				return err
			}
			return s.Manage(cmd.Context(), action, soc)
		},
	}
}

func statusCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:   "status [1|2]",
		Short: "Show mdrive service status",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			soc, err := socArg(args)
			if err != nil {
				return err
			}
			// Structured path: `md status --json` (and the text path) both use
			// CheckStates so "both" aggregates soc1+soc2 with a real non-zero on
			// any failure, fixing the old check that swallowed the soc1 result.
			states, err := s.CheckStates(cmd.Context(), soc)
			if err != nil {
				// CheckStates returns states + a non-nil error when any soc is
				// down; still render the states but surface the error to exit non-zero.
				if flagJSON(cmd) {
					_ = writeJSON(states)
				} else {
					for _, st := range states {
						fmt.Fprintf(os.Stderr, "[%s]服务状态: %s\n", st.SOC, st.State)
					}
				}
				return err
			}
			if flagJSON(cmd) {
				return writeJSON(states)
			}
			for _, st := range states {
				fmt.Fprintln(os.Stderr, "["+st.SOC+"]服务状态: "+st.State)
			}
			return nil
		},
	}
}

func logCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:   "log [1|2]",
		Short: "Follow mdrive.service journal (default soc1)",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			soc := "soc1"
			if len(args) > 0 && (args[0] == "soc2" || args[0] == "2") {
				soc = "soc2"
			} else if len(args) > 0 && !(args[0] == "soc1" || args[0] == "1") {
				return errBadSOC(args[0])
			}
			// journal payload to stdout so `md log 2 | grep ...` works (P1, #1).
			return s.Log(cmd.Context(), soc, os.Stdout)
		},
	}
}

func channelCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:     "channel [1|2] [-- <args...>]",
		Aliases: []string{"c"},
		Short:   "Launch DDS channel viewer (dtop→cyber_monitor fallback, default soc1)",
		Args:    cobra.ArbitraryArgs, // tail args after `--` are passed to the viewer
		RunE: func(cmd *cobra.Command, args []string) error {
			soc := "soc1"
			rest := args
			if len(rest) > 0 && (rest[0] == "soc1" || rest[0] == "1") {
				rest = rest[1:]
			} else if len(rest) > 0 && (rest[0] == "soc2" || rest[0] == "2") {
				soc = "soc2"
				rest = rest[1:]
			}
			return s.Channel(cmd.Context(), soc, rest)
		},
	}
}

func recordCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:   "record [on|off]",
		Short: "Start/stop the soc2 Recorder (default on)",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			action := "on"
			if len(args) > 0 {
				action = args[0]
			}
			return s.Recorder(cmd.Context(), action)
		},
	}
}

func remoteCmd() *cobra.Command {
	run := func(args []string) error {
		switch {
		case len(args) == 0:
			return cmdUsage("remote")
		case args[0] == "list":
			lines, e := remote.List(remotePath())
			if e != nil {
				return e
			}
			if lines == nil {
				_, err := stdoutP("暂无分支\n")
				return err
			}
			for _, l := range lines {
				_, _ = stdoutP(l + "\n")
			}
			return nil
		case args[0] == "add" && len(args) >= 3:
			plat := argOr(args, 3, "")
			added, e := remote.Add(remotePath(), args[1], args[2], plat)
			if e != nil {
				return e
			}
			label := args[1] + " " + args[2] + " " + plat
			// Human status to stderr so stdout stays machine-parseable (P1).
			if added {
				fmt.Fprintln(os.Stderr, "已添加: "+label)
			} else {
				fmt.Fprintln(os.Stderr, "配置 ["+label+"] 已存在")
			}
			return nil
		case args[0] == "del" && len(args) == 2:
			removed, e := remote.Del(remotePath(), args[1])
			if e != nil {
				return e
			}
			if removed {
				fmt.Fprintln(os.Stderr, "分支 ["+args[1]+"] 远程配置已删除")
			}
			return nil
		default:
			return cmdUsage("remote")
		}
	}

	return &cobra.Command{
		Use:   "remote <add|del|list>",
		Short: "Manage remote branch targets (~/.md_remotes)",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return run(args)
		},
	}
}

func checkCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:   "check",
		Short: "Run the environment self-check",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			return s.PreCheck(cmd.Context())
		},
	}
}

// moduleCmd implements `md m` (aliases module/mod): with no args it opens the
// Bubble Tea module menu (G4); with args `md m <start|stop|restart> <1|2>
// <mod...>` it runs a headless batch action (G4-a ModCtl).
func moduleCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:     "m [list|<start|stop|restart> <1|2> <mod...>]",
		Aliases: []string{"module", "mod"},
		Short:   "Module operations (menu in a TTY, plain list otherwise; <cmd> <soc> <module...> acts)",
		Args:    cobra.ArbitraryArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			// `md m list`/`ls`/`l` — scripted, plain-text module listing to stdout
			// (pipe-friendly; the menu path is TTY-only).
			if len(args) == 1 && (args[0] == "list" || args[0] == "ls" || args[0] == "l") {
				return moduleList(cmd.Context(), s)
			}
			if len(args) == 0 {
				// Bubble Tea menu requires a real terminal; a non-TTY stdout would
				// emit alt-screen escape bytes into the pipe. Degrade to the plain
				// listing instead (P1 non-TTY guard).
				if !isTerminal(stdoutfd()) {
					return moduleList(cmd.Context(), s)
				}
				return tui.RunModuleMenu(cmd.Context(), s)
			}
			if len(args) < 3 {
				return fmt.Errorf("用法: md m <start|stop|restart> <1(soc1)|2(soc2)> <模块名...>，或 md m list")
			}
			if err := s.ModCtl(cmd.Context(), args[0], args[1], args[2:]); err != nil {
				// The batch failure count is the process exit code (md.sh:849-850).
				var mbe *svc.ModuleBatchError
				if errors.As(err, &mbe) {
					return &ExitError{Code: mbe.Count, Err: err}
				}
				return err
			}
			return nil
		},
	}
}

// moduleList prints the combined module status as plain text to stdout
// (pipe-friendly, P1). It mirrors the TUI rows but without ANSI colors, so
// `md m list | grep -i camera` works.
func moduleList(ctx context.Context, s *svc.Svc) error {
	rows, err := s.FetchModules(ctx)
	if err != nil {
		return err
	}
	for _, r := range rows {
		line := svc.StripANSI(r.Render(""))
		if _, werr := stdoutP(line + "\n"); werr != nil {
			return werr
		}
	}
	return nil
}

// defaultUser mirrors md.sh's `id -un` fallback (the vmc install user).
func defaultUser(cfg config.Config) string {
	if u := os.Getenv("USER"); u != "" {
		return u
	}
	// md.sh's nvidia default.
	return "nvidia"
}

// upgradeCmd implements `md upgrade` (vmc::upgrade). It runs the pre-check,
// then the full multi-branch upgrade flow.
func upgradeCmd(vf *vmcflow.VMC, s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:   "upgrade",
		Short: "Upgrade installed packages to the latest remote versions",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			prePassed := s.PreCheck(cmd.Context()) == nil
			// The Bash version always prompts (md.sh:1419-1424): y/回车继续,
			// and only 'f' continues when the pre-check failed. Never run this
			// destructive upgrade without an explicit confirm (P0-4). --yes
			// skips the confirm only when the pre-check passed; a failed
			// pre-check still needs an explicit 'f' — never force a destructive
			// upgrade off a red pre-check just because of --yes.
			confirm := ""
			if !flagYes(cmd) {
				confirm = readLineStdin()
			} else if !prePassed {
				vf.Log.Err("升级前检查未通过，不能依赖 --yes 强制继续 (需要 'f')")
				return fmt.Errorf("已取消升级")
			}
			if prePassed {
				if confirm != "y" && confirm != "Y" && confirm != "" && confirm != "f" {
					vf.Log.Err("已取消升级")
					return fmt.Errorf("已取消升级") // md.sh returns 1 on cancel (md.sh:1421)
				}
			} else {
				if confirm != "f" {
					vf.Log.Err("已取消升级")
					return fmt.Errorf("已取消升级") // md.sh:1424
				}
			}
			port := vmcflow.UpgradePort{PreCheckPassed: prePassed, Confirm: confirm}
			return vf.Upgrade(cmd.Context(), port)
		},
	}
}

// installCmd implements `md install` (vmc::install). The vi-editor input is
// supplied via stdin (the CLI does not open $EDITOR; the operator pastes the
// version lines). This keeps the Go tool script-friendly.
func installCmd(vf *vmcflow.VMC, s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:     "install [version]",
		Aliases: []string{"i"},
		Short:   "Install package versions (scripted single-version, or paste all versions)",
		Args:    cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			// Scripted single-version: `md install <version>` → finstall
			// (vmc::install with an arg, md.sh:1975-1983).
			if len(args) == 1 {
				version := args[0]
				if !flagYes(cmd) && !(vmcflow.Confirm{Response: readLineStdin()}).Ask() {
					vf.Log.Warn("已取消安装")
					return fmt.Errorf("已取消安装") // md.sh:1986 returns 1 on cancel
				}
				// Bash finstall path (md.sh:1975-1983) never runs flow::pre; drop
				// the PreCheck the single-version path had added (P1-6).
				_ = s.Manage(cmd.Context(), "stop", "soc1")
				_ = s.Manage(cmd.Context(), "stop", "soc2")
				if err := vf.Clean(cmd.Context()); err != nil {
					return err
				}
				if err := vf.Finstall(cmd.Context(), version, ""); err != nil {
					vf.Log.Warn("安装失败，服务已停止，执行 md start 恢复运行")
					return err
				}
				return nil
			}

			// Interactive paste: `md install` → read all version lines from
			// stdin, extract and install each (vmc::install, md.sh).
			input, err := readAllStdin()
			if err != nil {
				return err
			}
			prePassed := s.PreCheck(cmd.Context()) == nil
			port := vmcflow.UpgradePort{PreCheckPassed: prePassed, Confirm: ""}
			return vf.Install(cmd.Context(), input, port)
		},
	}
}

// rollbackCmd implements `md rb [version] [name]` (vmc::rollback). It searches
// history, filters by exact column when a package is given, and installs the
// first candidate (the CLI's TUI picker is a later enhancement). The confirm
// prompt reads stdin.
func rollbackCmd(vf *vmcflow.VMC) *cobra.Command {
	return &cobra.Command{
		Use:     "rollback [version] [name]",
		Aliases: []string{"rb"},
		Short:   "Roll back a package to a selected historical version",
		Args:    cobra.MaximumNArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			version := argOr(args, 0, "")
			name := argOr(args, 1, "")
			exactCol := ""
			if name == "" && version == "" {
				// No args: md.sh flow reads the remote config. For the Go CLI we
				// require at least a version keyword to keep it non-interactive.
				return fmt.Errorf("用法: md rb <version关键字> [包名]，或 md rb - <包名关键字>")
			}
			if strings.HasPrefix(name, "=") {
				exactCol = strings.TrimPrefix(name, "=")
			}
			cands, err := vf.Rollback(cmd.Context(), version, name, exactCol)
			if err != nil {
				return err
			}
			if len(cands) == 0 {
				// md.sh returns 1 when nothing is found (md.sh:1709) — a script
				// must be able to distinguish "no rollback" from success.
				return fmt.Errorf("未搜索到可回滚版本")
			}
			// Auto-select the first (newest) candidate. The interactive picker
			// is a CLI-layer enhancement. --yes skips the confirm; otherwise it
			// reads stdin, and a cancel exits non-zero (md.sh returns 1).
			sel := cands[0]
			if !flagYes(cmd) {
				vf.Log.Warn("确定回滚 [%s] 到版本: %s ?", sel.Name, sel.Version)
				if !(vmcflow.Confirm{Response: readLineStdin()}).Ask() {
					return fmt.Errorf("已取消回滚")
				}
			}
			return vf.InstallRollback(cmd.Context(), sel, nil)
		},
	}
}
