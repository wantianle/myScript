package sshx

import (
	"errors"
	"fmt"
	"strings"
)

// Sentinel errors classify failures for callers that need to react
// differently to "the key/auth is wrong" versus "the host is unreachable or
// the link died".
var (
	// ErrAuthFailed wraps key and authentication failures: the key file is
	// missing, unreadable, over-permissive or unparsable, or the server
	// rejected the public key during the handshake. It mirrors what OpenSSH
	// reports before any session exists ("Permission denied",
	// "Bad permissions", "no such identity file").
	ErrAuthFailed = errors.New("ssh: authentication failed")

	// ErrConnFailed wraps transport-layer failures: TCP dial, the SSH
	// handshake, channel setup, a keepalive-detected dead link, a remote
	// side that vanished mid-command, or an operation attempted on a closed
	// Client. Remote exit codes never surface here (see ExecResult.ExitCode).
	ErrConnFailed = errors.New("ssh: connection failed")
)

// ExitError reports a remote command that ran to completion with a non-zero
// exit status. Exec deliberately does not use it (exit codes live in
// ExecResult.ExitCode); Stream and Interactive return it on the error channel
// because their callers follow the stream/return-value idiom and otherwise
// could not tell a completed-but-failed command from a transport failure.
type ExitError struct {
	Code int
}

func (e *ExitError) Error() string {
	return fmt.Sprintf("ssh: remote command exited with status %d", e.Code)
}

// preStartError wraps a transport failure that happened BEFORE the remote
// command was launched (session open, output pipe setup, exec request
// rejection). Retrying such an operation on a fresh connection cannot execute
// the command twice, which is what makes the dead→redial-once behaviour of
// Client safe.
type preStartError struct{ err error }

func (e *preStartError) Error() string { return e.err.Error() }
func (e *preStartError) Unwrap() error { return e.err }

func isPreStart(err error) bool {
	var pre *preStartError
	return errors.As(err, &pre)
}

// classifyDialError turns a golang.org/x/crypto/ssh dial/handshake error into
// an ErrAuthFailed or ErrConnFailed wrapped error, keeping the underlying
// detail for logs.
func classifyDialError(err error, addr string) error {
	if err == nil {
		return nil
	}
	msg := err.Error()
	if isAuthError(err) || strings.Contains(msg, "unable to authenticate") ||
		strings.Contains(msg, "no supported methods remain") ||
		strings.Contains(msg, "Permission denied") {
		return fmt.Errorf("%w: %v", ErrAuthFailed, err)
	}
	return fmt.Errorf("%w: dial %s: %v", ErrConnFailed, addr, err)
}

// isAuthError matches the ssh library's own auth-failure surfaces.
func isAuthError(err error) bool {
	var e interface{ AuthError() }
	if errors.As(err, &e) {
		return true
	}
	return false
}
