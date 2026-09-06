package sshx

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

// drainStream collects all chunks until BOTH channels close and returns the
// streamed stdout/stderr plus the first error (if any).
func drainStream(t *testing.T, chunks <-chan OutputChunk, errs <-chan error) (string, string, error) {
	t.Helper()
	var out, errOut strings.Builder
	var streamErr error
	chunksOpen, errsOpen := true, true
	for chunksOpen || errsOpen {
		select {
		case chunk, ok := <-chunks:
			if !ok {
				chunksOpen = false
				continue
			}
			if chunk.Stream == "stdout" {
				out.Write(chunk.Data)
			} else {
				errOut.Write(chunk.Data)
			}
		case err, ok := <-errs:
			if !ok {
				errsOpen = false
				continue
			}
			if err != nil {
				streamErr = err
			}
		case <-time.After(10 * time.Second):
			t.Fatal("drainStream timed out")
		}
	}
	return out.String(), errOut.String(), streamErr
}

// TestStreamDeliversIncrementalOutput is the journalctl -f path: output must
// arrive in multiple chunks as the command produces it, not only at exit.
func TestStreamDeliversIncrementalOutput(t *testing.T) {
	c, _ := testClient(t)
	chunks, errs := c.Stream(context.Background(), ExecRequest{
		Command: "printf 'a'; sleep 0.2; printf 'b'; sleep 0.2; printf 'c'",
	})
	stdout, _, streamErr := drainStream(t, chunks, errs)
	if streamErr != nil {
		t.Fatalf("Stream error = %v, want nil", streamErr)
	}
	if stdout != "abc" {
		t.Errorf("streamed stdout = %q, want %q", stdout, "abc")
	}
}

// TestStreamStderrAndExitError checks that stderr is delivered as its own
// stream and that a non-zero remote exit surfaces as *ExitError on the error
// channel (unlike Exec, where it would be ExecResult.ExitCode).
func TestStreamStderrAndExitError(t *testing.T) {
	c, _ := testClient(t)
	chunks, errs := c.Stream(context.Background(), ExecRequest{
		Command: "echo boom >&2; exit 3",
	})
	_, stderr, streamErr := drainStream(t, chunks, errs)

	if stderr != "boom\n" {
		t.Errorf("streamed stderr = %q, want %q", stderr, "boom\n")
	}
	var exitErr *ExitError
	if !errors.As(streamErr, &exitErr) {
		t.Fatalf("Stream error = %v, want *ExitError", streamErr)
	}
	if exitErr.Code != 3 {
		t.Errorf("ExitError.Code = %d, want 3", exitErr.Code)
	}
}

// TestStreamContextCancel stops a long-running follow (journalctl -f stands
// in) as soon as the caller cancels the context.
func TestStreamContextCancel(t *testing.T) {
	c, _ := testClient(t)

	ctx, cancel := context.WithCancel(context.Background())
	chunks, errs := c.Stream(ctx, ExecRequest{Command: "sleep 100"})
	time.Sleep(200 * time.Millisecond)
	cancel()

	var streamErr error
	select {
	case streamErr = <-errs:
	case <-time.After(5 * time.Second):
		t.Fatal("Stream did not return after context cancel")
	}
	if !errors.Is(streamErr, context.Canceled) {
		t.Fatalf("Stream error = %v, want context.Canceled", streamErr)
	}
	for range chunks {
		// drain whatever remains so the producer goroutine can finish
	}
}

// TestStreamZeroExitSendsNil ensures a clean zero-exit follow reports no
// error at all.
func TestStreamZeroExitSendsNil(t *testing.T) {
	c, _ := testClient(t)
	chunks, errs := c.Stream(context.Background(), ExecRequest{Command: "printf hi"})
	var out bytes.Buffer
	for chunk := range chunks {
		if chunk.Stream == "stdout" {
			out.Write(chunk.Data)
		}
	}
	if out.String() != "hi" {
		t.Errorf("stdout = %q, want %q", out.String(), "hi")
	}
	select {
	case err := <-errs:
		if err != nil {
			t.Fatalf("Stream error = %v, want nil", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("no terminal error received")
	}
}
