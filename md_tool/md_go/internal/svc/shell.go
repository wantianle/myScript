package svc

import (
	"context"
	"io"
	"os"
	"os/exec"
	"time"

	"mdrive/md/internal/config"
	"mdrive/md/internal/sshx"
)

// localShell executes commands on the machine running the tool (soc1). It uses
// the system shell via exec.CommandContext, capturing output for Exec and
// wiring the terminal through for Interactive.
type localShell struct{}

// NewLocal returns a Shell for the local (soc1) machine.
func NewLocal() Shell { return localShell{} }

func (localShell) Exec(ctx context.Context, command string) (ExecOut, error) {
	run := func() ExecOut {
		cmd := exec.CommandContext(ctx, "sh", "-c", command)
		var stdout, stderr []byte
		cmd.Stdout = &bufferingWriter{buf: &stdout}
		cmd.Stderr = &bufferingWriter{buf: &stderr}
		err := cmd.Run()
		code := 0
		if err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				code = ee.ExitCode()
			} else {
				code = -1
			}
		}
		return ExecOut{Stdout: string(stdout), Stderr: string(stderr), Code: code}
	}
	return run(), nil
}

func (localShell) Stream(ctx context.Context, command string) (<-chan Chunk, <-chan error) {
	chunks := make(chan Chunk)
	errs := make(chan error, 1)
	go func() {
		defer close(chunks)
		defer close(errs)
		cmd := exec.CommandContext(ctx, "sh", "-c", command)
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			errs <- err
			return
		}
		stderr, err := cmd.StderrPipe()
		if err != nil {
			errs <- err
			return
		}
		if err := cmd.Start(); err != nil {
			errs <- err
			return
		}
		var wg = make(chan struct{}, 1)
		go func() {
			defer func() { wg <- struct{}{} }()
			pump(ctx, stdout, "stdout", chunks)
		}()
		go func() {
			defer func() { wg <- struct{}{} }()
			pump(ctx, stderr, "stderr", chunks)
		}()
		err = cmd.Wait()
		<-wg
		<-wg
		if err != nil {
			errs <- err
		}
	}()
	return chunks, errs
}

func (localShell) Interactive(ctx context.Context, command string) error {
	cmd := exec.CommandContext(ctx, "sh", "-c", command)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func (localShell) Close() error { return nil }

// remoteShell executes commands on soc2 over ssh. It wraps a single pooled
// sshx.Client so repeated Exec calls in one operation reuse the connection
// (md.sh re-dials per call; Go pools them like the Bash sequential calls).
type remoteShell struct {
	client *sshx.Client
}

// NewRemote dials an sshx.Client to host and returns a Shell for it. host is
// the resolved endpoint host (soc2's IP when run from soc1, soc1's IP when run
// from soc2, from the platform.Topology). The sshx ClientConfig defaults (User
// from $USER, KeyPath ~/.ssh/id_ed25519, HostKeyCallback InsecureIgnoreHostKey)
// align with md.sh SSH_OPTS.
func NewRemote(ctx context.Context, cfg config.Config, host string) (Shell, error) {
	client, err := sshx.Dial(ctx, sshx.ClientConfig{Host: host})
	if err != nil {
		return nil, err
	}
	return &remoteShell{client: client}, nil
}

func (r *remoteShell) Exec(ctx context.Context, command string) (ExecOut, error) {
	res, err := r.client.Exec(ctx, sshx.ExecRequest{Command: command})
	if err != nil {
		return ExecOut{}, err
	}
	return ExecOut{Stdout: string(res.Stdout), Stderr: string(res.Stderr), Code: res.ExitCode}, nil
}

func (r *remoteShell) Stream(ctx context.Context, command string) (<-chan Chunk, <-chan error) {
	chunks, errs := r.client.Stream(ctx, sshx.ExecRequest{Command: command})
	out := make(chan Chunk)
	done := make(chan error, 1)
	go func() {
		defer close(out)
		defer close(done)
		for {
			select {
			case chunk, ok := <-chunks:
				if !ok {
					chunks = nil
					continue
				}
				select {
				case out <- Chunk{Stream: chunk.Stream, Data: chunk.Data}:
				case <-ctx.Done():
					return
				}
			case err, ok := <-errs:
				if !ok {
					errs = nil
					continue
				}
				if err != nil {
					done <- err
				}
				return
			case <-ctx.Done():
				done <- ctx.Err()
				return
			}
		}
	}()
	return out, done
}

func (r *remoteShell) Interactive(ctx context.Context, command string) error {
	return r.client.Interactive(ctx, sshx.InteractiveRequest{Shell: command})
}

func (r *remoteShell) Close() error { return r.client.Close() }

// bufferingWriter is an io.Writer that appends to a byte slice, avoiding the
// fixed-size buffer of the runner package for arbitrary-length command output.
type bufferingWriter struct{ buf *[]byte }

func (w *bufferingWriter) Write(p []byte) (int, error) {
	*w.buf = append(*w.buf, p...)
	return len(p), nil
}

// pump forwards reads from an io.ReadCloser to chunks until EOF or ctx done.
func pump(ctx context.Context, r io.Reader, stream string, chunks chan<- Chunk) {
	buf := make([]byte, 32*1024)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			select {
			case chunks <- Chunk{Stream: stream, Data: append([]byte(nil), buf[:n]...)}:
			case <-ctx.Done():
				return
			}
		}
		if err != nil {
			return
		}
	}
}

// sleepCtx sleeps 1s, returning early when ctx is cancelled (used by the soc1
// stop-polling loop so a cancelled operation does not wait the full window).
func sleepCtx(ctx context.Context) {
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
	}
}

// compile-time assertion that localShell/remoteShell satisfy Shell.
var _ Shell = localShell{}
var _ Shell = (*remoteShell)(nil)
