package sshx

import (
	"context"
	"errors"
	"io"
	"sync"
	"testing"
	"time"

	"mdrive/md/internal/sshtest"
)

// keepaliveLoop previously had zero test coverage: every integration test
// dials with KeepAliveInterval < 0 to keep the goroutine out of the way. These
// tests pin the loop's two contracts deterministically with fake connections
// (no real timeouts), plus one end-to-end run over the in-process server with
// the real md.sh default config.

// scriptedKeepaliveConn is a keepaliveConn whose SendRequest returns each
// scripted error once and then repeats the last one; an empty script always
// succeeds. Close counts its calls. keepaliveLoop spawns one SendRequest
// goroutine per tick, so all state is mutex-guarded.
type scriptedKeepaliveConn struct {
	mu     sync.Mutex
	script []error // per-call SendRequest errors; empty = always healthy
	calls  int
	closed int
}

func (f *scriptedKeepaliveConn) SendRequest(name string, wantReply bool, payload []byte) (bool, []byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	var err error
	switch {
	case len(f.script) == 0:
		err = nil
	case f.calls < len(f.script):
		err = f.script[f.calls]
	default:
		err = f.script[len(f.script)-1]
	}
	f.calls++
	return true, nil, err
}

func (f *scriptedKeepaliveConn) Close() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.closed++
	return nil
}

func (f *scriptedKeepaliveConn) snapshot() (calls, closed int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls, f.closed
}

// waitCalls blocks until SendRequest has been called at least min times.
func (f *scriptedKeepaliveConn) waitCalls(t *testing.T, min int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if calls, _ := f.snapshot(); calls >= min {
			return
		}
		time.Sleep(2 * time.Millisecond)
	}
	calls, _ := f.snapshot()
	t.Fatalf("SendRequest calls = %d after 5s, want >= %d", calls, min)
}

// TestKeepaliveLoopFailureAccounting is the ServerAliveInterval /
// ServerAliveCountMax semantic: consecutive failed keepalives must close the
// connection once the counter reaches countMax, a single success in between
// must reset the counter, and a healthy connection must never be closed.
func TestKeepaliveLoopFailureAccounting(t *testing.T) {
	errDead := errors.New("keepalive probe failed")
	cases := []struct {
		name      string
		script    []error
		countMax  int
		wantClose int
	}{
		{name: "consecutive failures reach countMax", script: []error{errDead}, countMax: 3, wantClose: 1},
		{name: "success in between resets the counter", script: []error{errDead, nil, errDead, errDead}, countMax: 2, wantClose: 1},
		{name: "healthy connection is never closed", script: nil, countMax: 2, wantClose: 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			conn := &scriptedKeepaliveConn{script: tc.script}
			stop := make(chan struct{})
			done := make(chan struct{})
			go keepaliveLoop(conn, stop, done, 2*time.Millisecond, tc.countMax)

			if tc.wantClose == 0 {
				// Healthy: let several probes go out and prove no teardown
				// happens, then ask the loop to stop.
				conn.waitCalls(t, 5)
				if calls, closed := conn.snapshot(); closed != 0 {
					t.Fatalf("healthy keepalive closed the connection after %d probes", calls)
				}
				close(stop)
			}
			select {
			case <-done:
			case <-time.After(5 * time.Second):
				t.Fatal("keepaliveLoop did not exit")
			}
			if _, closed := conn.snapshot(); closed != tc.wantClose {
				t.Errorf("Close calls = %d, want %d", closed, tc.wantClose)
			}
		})
	}
}

// TestKeepaliveLoopStopExitsWithoutProbing: a stop that arrives before the
// first tick must exit the loop without ever touching the connection — the
// client.Close() path must not send keepalives on a connection it is tearing
// down.
func TestKeepaliveLoopStopExitsWithoutProbing(t *testing.T) {
	conn := &scriptedKeepaliveConn{script: []error{errors.New("must not be called")}}
	stop := make(chan struct{})
	done := make(chan struct{})
	close(stop) // already torn down before the loop starts
	go keepaliveLoop(conn, stop, done, time.Millisecond, 2)

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("keepaliveLoop did not exit after stop")
	}
	if calls, closed := conn.snapshot(); calls != 0 || closed != 0 {
		t.Errorf("loop touched the connection (calls=%d closed=%d), want neither", calls, closed)
	}
}

// hangingKeepaliveConn never answers SendRequest until Close() is called: an
// unresponsive-but-open peer, exactly the case the bounded reply wait in
// keepaliveLoop exists for (x/crypto has no per-request deadline, so the loop
// must time the reply out itself).
type hangingKeepaliveConn struct {
	mu         sync.Mutex
	calls      int
	closeCalls int
	once       sync.Once
	unblock    chan struct{}
}

func newHangingKeepaliveConn() *hangingKeepaliveConn {
	return &hangingKeepaliveConn{unblock: make(chan struct{})}
}

func (h *hangingKeepaliveConn) SendRequest(name string, wantReply bool, payload []byte) (bool, []byte, error) {
	h.mu.Lock()
	h.calls++
	h.mu.Unlock()
	<-h.unblock // no reply until the connection is closed
	return false, nil, io.EOF
}

func (h *hangingKeepaliveConn) Close() error {
	h.mu.Lock()
	h.closeCalls++
	h.mu.Unlock()
	h.once.Do(func() { close(h.unblock) })
	return nil
}

// TestKeepaliveLoopTimesOutUnresponsivePeer: when SendRequest neither fails
// nor answers within one interval, every interval counts as a failure and the
// loop must Close the connection after countMax of them (the auto-teardown
// that makes in-flight operations fail fast on a dead peer).
func TestKeepaliveLoopTimesOutUnresponsivePeer(t *testing.T) {
	conn := newHangingKeepaliveConn()
	stop := make(chan struct{})
	done := make(chan struct{})
	go keepaliveLoop(conn, stop, done, 10*time.Millisecond, 2)

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		_ = conn.Close() // unblock straggler SendRequest goroutines first
		t.Fatal("keepaliveLoop did not close an unresponsive connection")
	}
	conn.mu.Lock()
	calls, closeCalls := conn.calls, conn.closeCalls
	conn.mu.Unlock()
	if calls < 2 {
		t.Errorf("SendRequest calls = %d, want >= 2 (one per timed-out interval)", calls)
	}
	if closeCalls != 1 {
		t.Errorf("Close calls = %d, want exactly 1", closeCalls)
	}
}

// TestKeepaliveDefaultDoesNotKillLongRunningExec is the Q5 acceptance case for
// a healthy connection: with the DEFAULT md.sh keepalive config (2s interval,
// countMax 2) on a real connection, a command spanning several keepalive ticks
// (sleep 5 → ticks at ~2s and ~4s) must complete normally. The pooled
// *ssh.Client must also be the SAME object afterwards — a healthy long command
// must never trigger a keepalive drop + redial.
func TestKeepaliveDefaultDoesNotKillLongRunningExec(t *testing.T) {
	srv := sshtest.NewServer(t)
	c := dialServerKeepalive(t, srv, 0) // 0 → resolveConfig default (2s / countMax 2)
	t.Cleanup(func() { _ = c.Close() })
	connBefore := c.SSHClient()
	if connBefore == nil {
		t.Fatal("SSHClient() = nil right after Dial")
	}

	start := time.Now()
	res, err := c.Exec(context.Background(), ExecRequest{Command: "sleep 5", Timeout: 15 * time.Second})
	if err != nil {
		t.Fatalf("Exec(sleep 5) under default keepalive = %v; a healthy connection must not be killed mid-command", err)
	}
	if res.ExitCode != 0 {
		t.Errorf("Exec(sleep 5) exit code = %d, want 0", res.ExitCode)
	}
	if elapsed := time.Since(start); elapsed < 4*time.Second {
		t.Errorf("Exec returned after %v, want >= 4s so the command spans 2 keepalive intervals", elapsed)
	}
	if got := c.SSHClient(); got != connBefore {
		t.Error("the pooled connection was replaced during a healthy long command; keepalive must not drop a live connection")
	}
}

// TestKeepaliveGoroutineLifecycle pins the connect() contract: the default
// config (interval 0) starts the goroutine, so its done channel stays open
// while it runs; a negative interval skips the goroutine and closes the done
// channel immediately.
func TestKeepaliveGoroutineLifecycle(t *testing.T) {
	srvEnabled := sshtest.NewServer(t)
	enabled := dialServerKeepalive(t, srvEnabled, 0)
	t.Cleanup(func() { _ = enabled.Close() })
	enabled.mu.Lock()
	doneEnabled := enabled.kaDone
	enabled.mu.Unlock()
	select {
	case <-doneEnabled:
		t.Error("default keepalive config must start the loop (kaDone open while it runs)")
	default:
	}

	srvDisabled := sshtest.NewServer(t)
	disabled := dialServer(t, srvDisabled) // -1 escape hatch
	t.Cleanup(func() { _ = disabled.Close() })
	disabled.mu.Lock()
	doneDisabled := disabled.kaDone
	disabled.mu.Unlock()
	select {
	case <-doneDisabled:
	default:
		t.Error("negative interval must not start the loop (kaDone closed immediately)")
	}
}
