package cli

import (
	"mdrive/md/internal/app"
	"mdrive/md/internal/config"
	"mdrive/md/internal/tui"

	"github.com/spf13/cobra"
)

type Options struct {
	ProgramName string
	Version     string
}

func NewRootCommand(opts Options) *cobra.Command {
	if opts.ProgramName == "" {
		opts.ProgramName = "md"
	}
	if opts.Version == "" {
		opts.Version = "0.1.0-dev"
	}

	cfg := config.FromEnv()
	session := app.NewSession(cfg)

	if opts.ProgramName == "tag" {
		return newTagRootCommand(session, opts.Version)
	}

	root := &cobra.Command{
		Use:           "md",
		Short:         "MDrive vehicle operations tool",
		Version:       opts.Version,
		SilenceUsage:  true,
		SilenceErrors: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			return tui.Run(cmd.Context(), session.Config, opts.Version)
		},
	}

	root.SetVersionTemplate("md {{.Version}}\n")
	root.AddCommand(newTagCommand(session))

	return root
}
