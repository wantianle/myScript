package cli

import (
	"mdrive/md/internal/config"

	"github.com/spf13/cobra"
)

// Options configures the root command.
type Options struct {
	ProgramName string
	Version     string
}

// NewRootCommand builds the md command tree. G3 ships the service-control
// surface: start/stop/restart/status/log/c(channel)/record/remote/check. The
// TUI-backed `md m` module menu and `md e` export are wired in G4.
func NewRootCommand(opts Options) *cobra.Command {
	if opts.ProgramName == "" {
		opts.ProgramName = "md"
	}
	if opts.Version == "" {
		opts.Version = "0.1.0-dev"
	}

	cfg := config.FromEnv()
	root := newServiceRoot(cfg, opts.ProgramName, opts.Version)
	root.SetVersionTemplate(opts.ProgramName + " {{.Version}}\n")
	return root
}
