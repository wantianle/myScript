package cli

import (
	"errors"
	"fmt"
)

// ExitError wraps an error with a process exit code so a command can signal a
// specific non-zero status (md.sh sets shell exit codes like the module-batch
// failure count). The main function inspects errors for this type and uses
// Code instead of the default 1.
type ExitError struct {
	Code int
	Err  error
}

func (e *ExitError) Error() string {
	if e.Err != nil {
		return e.Err.Error()
	}
	return fmt.Sprintf("exit code %d", e.Code)
}

func (e *ExitError) Unwrap() error { return e.Err }

// ExitCodeOf returns the ExitError code embedded in err (wrapped or direct),
// or 1 when err is non-nil and not an ExitError, or 0 when err is nil. It is
// how main maps a command error to a process exit code.
func ExitCodeOf(err error) int {
	if err == nil {
		return 0
	}
	var ee *ExitError
	if errors.As(err, &ee) {
		return ee.Code
	}
	return 1
}
