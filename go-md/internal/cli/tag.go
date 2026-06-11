package cli

import (
	"fmt"
	"strings"

	"mdrive/md/internal/app"

	"github.com/spf13/cobra"
)

func newTagRootCommand(session *app.Session, version string) *cobra.Command {
	root := &cobra.Command{
		Use:           "tag",
		Short:         "Tag road-test moments",
		Version:       version,
		SilenceUsage:  true,
		SilenceErrors: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}
	root.SetVersionTemplate("tag {{.Version}}\n")
	root.AddCommand(newTagLeafCommands(session)...)
	return root
}

func newTagCommand(session *app.Session) *cobra.Command {
	cmd := &cobra.Command{
		Use:           "tag",
		Short:         "Tag road-test moments",
		SilenceErrors: true,
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}
	cmd.AddCommand(newTagLeafCommands(session)...)
	return cmd
}

func newTagLeafCommands(session *app.Session) []*cobra.Command {
	info := &cobra.Command{
		Use:   "info <message>",
		Short: "Record a tag message",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			_ = session
			message := strings.Join(args, " ")
			return notImplemented(cmd, "tag info", fmt.Sprintf("message=%q", message))
		},
	}

	list := &cobra.Command{
		Use:   "list",
		Short: "List recorded tags",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			_ = session
			return notImplemented(cmd, "tag list", "")
		},
	}

	exp := &cobra.Command{
		Use:   "exp",
		Short: "Export tag-related records",
		RunE: func(cmd *cobra.Command, args []string) error {
			_ = session
			date, _ := cmd.Flags().GetString("date")
			indexes, _ := cmd.Flags().GetStringArray("index")
			clip, _ := cmd.Flags().GetBool("clip")
			dryRun, _ := cmd.Flags().GetBool("dry-run")
			detail := fmt.Sprintf("date=%q index=%v clip=%v dry-run=%v args=%v", date, indexes, clip, dryRun, args)
			return notImplemented(cmd, "tag exp", detail)
		},
	}
	exp.Flags().StringP("date", "d", "", "tag date in YYYYMMDD")
	exp.Flags().StringArrayP("index", "i", nil, "tag index, repeatable during the scaffold stage")
	exp.Flags().Bool("clip", false, "clip mcap files before export")
	exp.Flags().Bool("dry-run", false, "resolve export tasks without copying files")

	return []*cobra.Command{info, list, exp}
}

func notImplemented(cmd *cobra.Command, name string, detail string) error {
	if detail != "" {
		cmd.Printf("%s scaffold received: %s\n", name, detail)
	}
	return fmt.Errorf("%s is not implemented in the Go scaffold yet", name)
}
