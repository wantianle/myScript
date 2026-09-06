package cli

import (
	"mdrive/md/internal/config"
	"mdrive/md/internal/logx"
	"mdrive/md/internal/remote"
	"mdrive/md/internal/svc"

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

	root := &cobra.Command{
		Use:           programName,
		Short:         "MDrive vehicle operations tool",
		Version:       version,
		SilenceUsage:  true,
		SilenceErrors: true,
	}

	root.AddCommand(
		manageCmd(s, "start"),
		manageCmd(s, "stop"),
		manageCmd(s, "restart"),
		statusCmd(s),
		logCmd(s),
		channelCmd(s),
		recordCmd(s),
		remoteCmd(),
		checkCmd(s),
	)

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
			return s.Check(cmd.Context(), soc)
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
			return s.Log(cmd.Context(), soc, osStderr())
		},
	}
}

func channelCmd(s *svc.Svc) *cobra.Command {
	return &cobra.Command{
		Use:     "channel [1|2]",
		Aliases: []string{"c"},
		Short:   "Launch dtop channel viewer (default soc1)",
		Args:    cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			soc := "soc1"
			if len(args) > 0 {
				soc = args[0]
			}
			return s.Channel(cmd.Context(), soc)
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
			if added {
				_, _ = stdoutP("已添加: " + label + "\n")
			} else {
				_, _ = stdoutP("配置 [" + label + "] 已存在\n")
			}
			return nil
		case args[0] == "del" && len(args) == 2:
			removed, e := remote.Del(remotePath(), args[1])
			if e != nil {
				return e
			}
			if removed {
				_, _ = stdoutP("分支 [" + args[1] + "] 远程配置已删除\n")
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
