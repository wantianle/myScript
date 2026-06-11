package pages

import "fmt"

type HomeOptions struct {
	Version             string
	BagRoot             string
	TagExportRoot       string
	MaxRecordLagSeconds int
	QuitHelp            string
}

func Home(opts HomeOptions) string {
	return fmt.Sprintf(
		"md Go TUI scaffold\n\nversion: %s\nbag root: %s\ntag export root: %s\nmax record lag: %ds\n\nNext: migrate tag store and record locator.\n%s",
		opts.Version,
		opts.BagRoot,
		opts.TagExportRoot,
		opts.MaxRecordLagSeconds,
		opts.QuitHelp,
	)
}
