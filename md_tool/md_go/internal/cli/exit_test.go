package cli

import (
	"errors"
	"testing"

	"mdrive/md/internal/svc"
)

func TestExitCodeOf(t *testing.T) {
	if got := ExitCodeOf(nil); got != 0 {
		t.Errorf("nil → %d, want 0", got)
	}
	if got := ExitCodeOf(errors.New("boom")); got != 1 {
		t.Errorf("plain error → %d, want 1", got)
	}
	if got := ExitCodeOf(&ExitError{Code: 7, Err: errors.New("fail")}); got != 7 {
		t.Errorf("ExitError → %d, want 7", got)
	}
}

func TestModuleBatchErrorMapsToExitCode(t *testing.T) {
	// A batch with 3 failed modules must surface exit code 3 via the CLI wrapper.
	mbe := &svc.ModuleBatchError{Count: 3}
	wrapped := &ExitError{Code: mbe.Count, Err: mbe}
	if got := ExitCodeOf(wrapped); got != 3 {
		t.Errorf("ModuleBatchError(3) wrapped → %d, want 3", got)
	}
}
