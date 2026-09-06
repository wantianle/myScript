package sshx

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"sync"

	"golang.org/x/crypto/ssh"
)

// Exec runs req.Command on the pooled connection and captures its stdout and
// stderr (md.sh `ssh -n ${SSH_OPTS[@]} user@host "cmd"`, but without needing
// the openssh binary).
//
// The error contract: nil means the command ran and exited (exit code — 0 or
// not — is in ExecResult.ExitCode, mirroring how md.sh inspects `$?`). Any
// non-nil error is a transport-layer failure (ErrAuthFailed / ErrConnFailed /
// context deadline or cancellation).
//
// req.Timeout is a per-command wall-clock budget. Zero falls back to 30s so a
// hung remote command cannot occupy the pooled connection forever; when it
// fires, the connection is dropped, killing the remote command the same way
// Ctrl-C on `ssh host 'cmd'` does. Pass a caller context with its own earlier
// deadline to override.
func (c *Client) Exec(ctx context.Context, req ExecRequest) (ExecResult, error) {
	c.opMu.Lock()
	defer c.opMu.Unlock()

	timeout := req.Timeout
	if timeout <= 0 {
		timeout = defaultExecTimeout
	}
	opCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	var res ExecResult
	err := c.runOnConn(opCtx, func(conn *ssh.Client) error {
		return execCapture(conn, opCtx, req, &res)
	})
	if err != nil {
		return ExecResult{}, err
	}
	return res, nil
}

// Stream runs req.Command and delivers its stdout/stderr incrementally as
// OutputChunk values — the journalctl -f path that md.sh implements with
// `ssh -t ... 'sudo journalctl -f'` and that a TUI viewport consumes line by
// line.
//
// The chunk channel closes when the command ends (or fails); the error
// channel carries at most one terminal error. Remote non-zero exits arrive as
// *ExitError on the error channel (unlike Exec, where the code travels in
// ExecResult). Unlike Exec there is NO implicit 30s budget: a `journalctl -f`
// follow runs until the caller cancels ctx — md.sh runs it until Ctrl-C. An
// explicit req.Timeout still bounds the stream.
func (c *Client) Stream(ctx context.Context, req ExecRequest) (<-chan OutputChunk, <-chan error) {
	chunks := make(chan OutputChunk)
	errs := make(chan error, 1)

	go func() {
		defer close(chunks)
		defer close(errs)

		c.opMu.Lock()
		defer c.opMu.Unlock()

		opCtx := ctx
		if req.Timeout > 0 {
			var cancel context.CancelFunc
			opCtx, cancel = context.WithTimeout(ctx, req.Timeout)
			defer cancel()
		}
		err := c.runOnConn(opCtx, func(conn *ssh.Client) error {
			return streamCommand(conn, opCtx, req, chunks)
		})
		if err != nil {
			errs <- err
		}
	}()

	return chunks, errs
}

// execCapture runs one command on a session with full capture semantics. The
// caller's ctx is watched from the moment the remote command starts: when it
// fires (timeout budget exhausted or caller cancellation) the session channel
// and the underlying connection are closed, which makes the remote sshd hang
// up the command.
//
// Failures from session creation and from the exec request itself (before the
// remote command could possibly run) are wrapped in preStartError so
// runOnConn can safely retry once on a fresh connection.
func execCapture(conn *ssh.Client, ctx context.Context, req ExecRequest, res *ExecResult) error {
	session, err := conn.NewSession()
	if err != nil {
		return &preStartError{err: err}
	}
	defer session.Close()

	var stdout, stderr bytes.Buffer
	session.Stdout = &stdout
	session.Stderr = &stderr
	if req.Stdin != nil {
		session.Stdin = req.Stdin
	}
	// Stdin == nil reads from an empty buffer and immediately CloseWrites,
	// which is the ssh -n /dev/null semantic.

	if err := session.Start(req.Command); err != nil {
		return &preStartError{err: err}
	}

	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
		case <-done:
			return // command already finished; nothing to kill
		}
		select {
		case <-done:
			return // finished while we woke up; keep the connection healthy
		default:
		}
		// Kill the remote command: closing the session channel and the
		// connection makes sshd hang up the process group (md.sh ^C).
		_ = session.Close()
		_ = conn.Close()
	}()
	waitErr := session.Wait()
	close(done)

	res.Stdout = stdout.Bytes()
	res.Stderr = stderr.Bytes()

	if waitErr == nil {
		res.ExitCode = 0
		return nil
	}
	// A remote non-zero exit is a result, not an error (Exec contract).
	var exitErr *ssh.ExitError
	if errors.As(waitErr, &exitErr) {
		res.ExitCode = exitErr.ExitStatus()
		return nil
	}
	if ctx.Err() != nil {
		return fmt.Errorf("%w: %v", ctx.Err(), waitErr)
	}
	return waitErr
}

// streamCommand runs one command on a session and pushes its stdout and
// stderr to chunks as they arrive. Pre-start failures (session, pipes, exec
// request) are wrapped in preStartError.
func streamCommand(conn *ssh.Client, ctx context.Context, req ExecRequest, chunks chan<- OutputChunk) error {
	session, err := conn.NewSession()
	if err != nil {
		return &preStartError{err: err}
	}
	defer session.Close()

	stdout, err := session.StdoutPipe()
	if err != nil {
		return &preStartError{err: err}
	}
	stderr, err := session.StderrPipe()
	if err != nil {
		return &preStartError{err: err}
	}
	if req.Stdin != nil {
		session.Stdin = req.Stdin
	}
	if err := session.Start(req.Command); err != nil {
		return &preStartError{err: err}
	}

	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
		case <-done:
			return // command already finished; nothing to kill
		}
		select {
		case <-done:
			return // finished while we woke up; keep the connection healthy
		default:
		}
		_ = session.Close()
		_ = conn.Close()
	}()

	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		pumpStream(ctx, stdout, "stdout", chunks)
	}()
	go func() {
		defer wg.Done()
		pumpStream(ctx, stderr, "stderr", chunks)
	}()

	waitErr := session.Wait()
	close(done)
	wg.Wait() // drain everything the remote produced before reporting the end

	if waitErr == nil {
		return nil
	}
	var exitErr *ssh.ExitError
	if errors.As(waitErr, &exitErr) {
		return &ExitError{Code: exitErr.ExitStatus()}
	}
	if ctx.Err() != nil {
		return fmt.Errorf("%w: %v", ctx.Err(), waitErr)
	}
	return waitErr
}

// pumpStream forwards reads from a session output pipe into chunks until the
// stream ends or the consumer goes away (ctx done).
func pumpStream(ctx context.Context, r io.Reader, stream string, chunks chan<- OutputChunk) {
	buf := make([]byte, 32*1024)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			select {
			case chunks <- OutputChunk{Stream: stream, Data: append([]byte(nil), buf[:n]...)}:
			case <-ctx.Done():
				return
			}
		}
		if err != nil {
			return
		}
	}
}
