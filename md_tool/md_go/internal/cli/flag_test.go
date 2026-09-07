package cli

import (
	"bytes"
	"testing"

	"github.com/spf13/cobra"
)

// probeResult returns the flagYes value observed by a probe subcommand.
func probeFlagValue(t *testing.T, args []string) bool {
	t.Helper()
	root := &cobra.Command{Use: "md"}
	var yes bool
	root.PersistentFlags().BoolVar(&yes, "yes", false, "assume yes")
	seen := false
	child := &cobra.Command{
		Use: "probe",
		Run: func(cmd *cobra.Command, args []string) {
			seen = flagYes(cmd)
		},
	}
	root.AddCommand(child)
	root.SetArgs(args)
	root.SetOut(&bytes.Buffer{})
	root.SetErr(&bytes.Buffer{})
	if err := root.Execute(); err != nil {
		t.Fatalf("execute: %v", err)
	}
	return seen
}

func TestFlagYesPropagates(t *testing.T) {
	if probeFlagValue(t, []string{"probe"}) {
		t.Error("without --yes, flagYes should be false")
	}
	if !probeFlagValue(t, []string{"probe", "--yes"}) {
		t.Error("with --yes, flagYes should be true")
	}
}
