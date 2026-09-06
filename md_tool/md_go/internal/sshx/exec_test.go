package sshx

import (
	"bytes"
	"context"
	"errors"
	"net"
	"strconv"
	"testing"
	"time"

	"mdrive/md/internal/sshtest"
)

// testClient dials the in-process server with keepalive disabled (negative
// interval escape hatch) so tests are deterministic.
func testClient(t *testing.T) (*Client, *sshtest.Server) {
	t.Helper()
	srv := sshtest.NewServer(t)
	c := dialServer(t, srv)
	t.Cleanup(func() { _ = c.Close() })
	return c, srv
}

func dialServer(t *testing.T, srv *sshtest.Server) *Client {
	t.Helper()
	return dialServerKeepalive(t, srv, -1)
}

// dialServerKeepalive dials the in-process server with the given keepalive
// interval. A negative value disables the goroutine (the deterministic default
// for most tests); zero asks resolveConfig for the md.sh default (2s interval
// / countMax 2) and therefore exercises the real default configuration over a
// live connection with the keepalive goroutine running.
func dialServerKeepalive(t *testing.T, srv *sshtest.Server, interval time.Duration) *Client {
	t.Helper()
	host, portStr, err := net.SplitHostPort(srv.Addr())
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c, err := Dial(ctx, ClientConfig{
		User:              sshtest.User,
		Host:              host,
		Port:              port,
		KeyPath:           srv.ClientKeyPath(),
		KeepAliveInterval: interval,
	})
	if err != nil {
		t.Fatalf("Dial: %v", err)
	}
	return c
}

func TestExecExitCodePreserved(t *testing.T) {
	c, _ := testClient(t)
	ctx := context.Background()

	cases := []struct {
		name string
		cmd  string
		want int
	}{
		{name: "zero exit", cmd: "exit 0", want: 0},
		{name: "exit three", cmd: "exit 3", want: 3},
		{name: "nonzero via command status", cmd: "false", want: 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			res, err := c.Exec(ctx, ExecRequest{Command: tc.cmd})
			if err != nil {
				t.Fatalf("Exec(%q) = %v; a remote exit code must not be an error", tc.cmd, err)
			}
			if res.ExitCode != tc.want {
				t.Errorf("Exec(%q) exit code = %d, want %d", tc.cmd, res.ExitCode, tc.want)
			}
		})
	}
}

// TestExecStdoutStderrSplit checks that stdout and stderr arrive on separate
// capture buffers, mirroring how md.sh uses `2>` redirection to separate the
// remote streams.
func TestExecStdoutStderrSplit(t *testing.T) {
	c, _ := testClient(t)
	res, err := c.Exec(context.Background(), ExecRequest{Command: "printf out; printf err >&2"})
	if err != nil {
		t.Fatal(err)
	}
	if string(res.Stdout) != "out" {
		t.Errorf("Stdout = %q, want %q", res.Stdout, "out")
	}
	if string(res.Stderr) != "err" {
		t.Errorf("Stderr = %q, want %q", res.Stderr, "err")
	}
}

func TestExecCapturesLargeStdout(t *testing.T) {
	c, _ := testClient(t)
	res, err := c.Exec(context.Background(), ExecRequest{Command: "head -c 1000000 /dev/zero | tr '\\0' 'a'"})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Stdout) != 1000000 {
		t.Errorf("captured %d bytes, want 1000000", len(res.Stdout))
	}
}

// TestExecRelaysStdin checks ExecRequest.Stdin reaches the remote command
// (md.sh's interactive `ssh` forwards the terminal; the pure client forwards
// whatever reader the caller supplies, nil meaning /dev/null).
func TestExecRelaysStdin(t *testing.T) {
	c, _ := testClient(t)
	res, err := c.Exec(context.Background(), ExecRequest{
		Command: "cat",
		Stdin:   bytes.NewBufferString("hello-from-client"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if string(res.Stdout) != "hello-from-client" {
		t.Errorf("cat output = %q, want %q", res.Stdout, "hello-from-client")
	}
}

func TestExecNilStdinIsDevNull(t *testing.T) {
	c, _ := testClient(t)
	// `cat` with /dev/null stdin exits 0 immediately instead of hanging.
	res, err := c.Exec(context.Background(), ExecRequest{Command: "cat"})
	if err != nil {
		t.Fatal(err)
	}
	if res.ExitCode != 0 || len(res.Stdout) != 0 {
		t.Errorf("cat with nil stdin: exit=%d stdout=%q, want clean EOF", res.ExitCode, res.Stdout)
	}
}

// TestExecTimeout verifies the per-command wall-clock budget: a remote
// command that runs past the context deadline is killed and the caller gets
// context.DeadlineExceeded promptly (the 30s default fallback protects
// against hung commands, an explicit earlier ctx deadline wins).
func TestExecTimeout(t *testing.T) {
	c, _ := testClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := c.Exec(ctx, ExecRequest{Command: "sleep 5"})
	elapsed := time.Since(start)

	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Exec error = %v, want context.DeadlineExceeded", err)
	}
	if elapsed > 3*time.Second {
		t.Errorf("Exec took %v to time out, want < 3s (remote must be killed)", elapsed)
	}
}

// TestExecContextCancel mirrors a user pressing Ctrl-C during a non-streamed
// command: the operation returns promptly with context.Canceled.
func TestExecContextCancel(t *testing.T) {
	c, _ := testClient(t)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		_, err := c.Exec(ctx, ExecRequest{Command: "sleep 10"})
		done <- err
	}()
	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Exec error = %v, want context.Canceled", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Exec did not return after context cancel")
	}
}

// TestDialAuthRejected checks the ErrAuthFailed classification when the
// server rejects the public key (md.sh's "Permission denied (publickey)").
func TestDialAuthRejected(t *testing.T) {
	srv := sshtest.NewServer(t, sshtest.WithRejectAuth())
	host, portStr, _ := net.SplitHostPort(srv.Addr())
	port, _ := strconv.Atoi(portStr)
	_, err := Dial(context.Background(), ClientConfig{
		User: sshtest.User, Host: host, Port: port, KeyPath: srv.ClientKeyPath(),
	})
	if !errors.Is(err, ErrAuthFailed) {
		t.Fatalf("Dial with rejected key = %v, want ErrAuthFailed", err)
	}
}

// TestPingReachable runs the reachability probe over a connection dialed with
// the DEFAULT keepalive config (zero interval → resolveConfig's 2s / countMax
// 2), so the keepalive goroutine is genuinely running on a real connection —
// the config md.sh ships with.
func TestPingReachable(t *testing.T) {
	srv := sshtest.NewServer(t)
	c := dialServerKeepalive(t, srv, 0)
	t.Cleanup(func() { _ = c.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Ping(ctx); err != nil {
		t.Fatalf("Ping = %v, want nil for reachable server", err)
	}
}

// TestPingUnreachable: once the server is fully closed, Ping must fail with
// ErrConnFailed (the md.sh `ssh ... exit` probe returning false).
func TestPingUnreachable(t *testing.T) {
	srv := sshtest.NewServer(t)
	c := dialServer(t, srv)
	defer c.Close()
	srv.Close() // kill listener and connection

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Ping(ctx); !errors.Is(err, ErrConnFailed) {
		t.Fatalf("Ping after server close = %v, want ErrConnFailed", err)
	}
}

// TestDeadLinkFailsInFlightFast: when the server drops the connection while a
// command is running, the in-flight Exec must fail promptly (channel
// teardown), not hang until the remote command would have finished. This is
// the keepalive-less analogue of ServerAliveCountMax teardown.
func TestDeadLinkFailsInFlightFast(t *testing.T) {
	c, srv := testClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	errCh := make(chan error, 1)
	go func() {
		_, err := c.Exec(ctx, ExecRequest{Command: "sleep 30"})
		errCh <- err
	}()

	time.Sleep(300 * time.Millisecond) // let the remote command start
	start := time.Now()
	srv.CloseConns()

	select {
	case err := <-errCh:
		if !errors.Is(err, ErrConnFailed) {
			t.Fatalf("Exec error = %v, want ErrConnFailed", err)
		}
		if elapsed := time.Since(start); elapsed > 5*time.Second {
			t.Errorf("dead-link failure took %v, want < 5s", elapsed)
		}
	case <-time.After(8 * time.Second):
		t.Fatal("in-flight Exec hung after the connection was dropped")
	}
}

// TestRedialOnceAfterDeadLink: after the pooled connection died and the
// failing op reported ErrConnFailed, the NEXT operation transparently dials a
// fresh connection and succeeds — md.sh's per-command `ssh` process is the
// equivalent of always working on a fresh connection.
func TestRedialOnceAfterDeadLink(t *testing.T) {
	c, srv := testClient(t)
	srv.CloseConns() // kill the connection between ops

	res, err := c.Exec(context.Background(), ExecRequest{Command: "echo alive"})
	if err != nil {
		t.Fatalf("Exec after dead link = %v, want auto-redial success", err)
	}
	if !bytes.Contains(res.Stdout, []byte("alive")) {
		t.Errorf("stdout = %q, want %q", res.Stdout, "alive")
	}
}

func TestCloseStopsFurtherOps(t *testing.T) {
	c, _ := testClient(t)
	_ = c.Close()
	if _, err := c.Exec(context.Background(), ExecRequest{Command: "echo x"}); !errors.Is(err, ErrConnFailed) {
		t.Fatalf("Exec on closed client = %v, want ErrConnFailed", err)
	}
}

func TestSSHClientReturnsPooledConn(t *testing.T) {
	c, _ := testClient(t)
	conn := c.SSHClient()
	if conn == nil {
		t.Fatal("SSHClient() = nil right after Dial, want the pooled connection")
	}
}
