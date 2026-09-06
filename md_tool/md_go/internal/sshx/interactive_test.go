package sshx

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"testing"
	"time"

	"mdrive/md/internal/sshtest"
)

// TestBuildRemoteCommand mirrors the svc::channel md.sh:791 composition:
//
//	export MDRIVE_ROOT_DIR='/mdrive' && export ... && source ... && dtop
//
// Env values are expanded LOCALLY (os.ExpandEnv — the double-quoted md.sh
// string lets the local bash substitute first) and the expanded value is then
// always quoted, so the remote shell never re-expands anything.
func TestBuildRemoteCommand(t *testing.T) {
	t.Setenv("GLOG_log_dir", "/mnt/ufs_data/project/data log") // local value (with a space)
	req := InteractiveRequest{
		Shell: "dtop",
		Env: []string{
			"MDRIVE_ROOT_DIR=/mdrive",
			"GLOG_log_dir=$GLOG_log_dir", // expanded locally, then quoted
			"SPACED_VALUE=a b",
		},
		Source: []string{"/opt/minieye/setup.sh"},
	}
	want := "export MDRIVE_ROOT_DIR=/mdrive && " +
		"export GLOG_log_dir='/mnt/ufs_data/project/data log' && " +
		"export SPACED_VALUE='a b' && " +
		"source /opt/minieye/setup.sh && dtop"
	if got := buildRemoteCommand(req); got != want {
		t.Errorf("buildRemoteCommand =\n  %q\nwant\n  %q", got, want)
	}
}

// TestRenderEnvNeverShipsExpansionSyntax pins the ${...} remediation: a
// value like "${GLOG_log_dir:-/mnt/...}" is expanded locally instead of being
// shipped verbatim for remote expansion. os.ExpandEnv has no bash-style
// `:-default` syntax, so an unset variable expands to empty; the remote shell
// receives the locally-computed literal either way.
func TestRenderEnvNeverShipsExpansionSyntax(t *testing.T) {
	got := renderEnv("GLOG_log_dir=${GLOG_log_dir:-/mnt/ufs_data/project/data/log}")
	if got != "GLOG_log_dir=''" {
		t.Errorf("renderEnv = %q, want %q (locally expanded, no remote expansion)", got, "GLOG_log_dir=''")
	}
}

func TestBuildRemoteCommandEmptyShell(t *testing.T) {
	// No Shell: a pure `export`+`source` prefix is still a valid command line.
	got := buildRemoteCommand(InteractiveRequest{Env: []string{"A=1"}})
	if got != "export A=1" {
		t.Errorf("buildRemoteCommand = %q, want %q", got, "export A=1")
	}
}

func TestShellQuote(t *testing.T) {
	cases := []struct{ in, want string }{
		{"/mdrive/setup.sh", "/mdrive/setup.sh"}, // safe: verbatim
		{"a b", "'a b'"},
		{"it's", `'it'\''s'`},
	}
	for _, tc := range cases {
		if got := shellQuote(tc.in); got != tc.want {
			t.Errorf("shellQuote(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// TestInteractiveSSHArgs checks the system-ssh argv mirrors the md.sh
// SSH_OPTS plus -t (md.sh:183/:490/:725/:791), with the remote command as a
// single argv element at the end. The zero-value InteractiveRequest must add
// -t (ForceNoTTY default false), and ForceNoTTY:true must add -T instead.
func TestInteractiveSSHArgs(t *testing.T) {
	cfg := ClientConfig{
		User: "root", Host: "192.168.10.3", Port: 2222, KeyPath: "/home/x/.ssh/id_ed25519",
		DialTimeout: 2 * time.Second, KeepAliveInterval: 2 * time.Second, KeepAliveCountMax: 2,
	}
	remote := "dtop"
	args := interactiveSSHArgs(cfg, InteractiveRequest{}, remote)

	if args[len(args)-1] != remote {
		t.Errorf("last argv = %q, want the remote command as a single argv element", args[len(args)-1])
	}
	joined := strings.Join(args, " ")
	for _, want := range []string{
		"-t", "-o", "ConnectTimeout=2", "-o", "ServerAliveInterval=2",
		"-o", "ServerAliveCountMax=2", "-o", "StrictHostKeyChecking=no",
		"-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
		"-p", "2222", "-i", "/home/x/.ssh/id_ed25519", "root@192.168.10.3",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("argv missing %q:\n  %v", want, args)
		}
	}
	if strings.Contains(joined, "-T") {
		t.Errorf("default InteractiveRequest must add -t, not -T:\n  %v", args)
	}

	argsNoTTY := interactiveSSHArgs(cfg, InteractiveRequest{ForceNoTTY: true}, remote)
	if !strings.Contains(strings.Join(argsNoTTY, " "), "-T") {
		t.Errorf("ForceNoTTY=true must add -T:\n  %v", argsNoTTY)
	}
	if strings.Contains(strings.Join(argsNoTTY, " "), " -t ") {
		t.Errorf("ForceNoTTY=true must not add -t:\n  %v", argsNoTTY)
	}
}

func TestInteractiveSSHArgsDefaultPortOmitsDashP(t *testing.T) {
	cfg := ClientConfig{
		User: "u", Host: "h", KeyPath: "/k",
		DialTimeout: 2 * time.Second, KeepAliveInterval: 2 * time.Second, KeepAliveCountMax: 2,
	}
	args := interactiveSSHArgs(cfg, InteractiveRequest{}, "cmd")
	joined := strings.Join(args, " ")
	if strings.Contains(joined, "-p") {
		t.Errorf("default port 22 must not add -p:\n  %v", args)
	}
	if !strings.Contains(joined, "u@h") {
		t.Errorf("argv missing user@host:\n  %v", args)
	}
}

// ---- Interactive end-to-end tests (real system ssh against the in-process
// server, ssh -T so no local pty is required and CI can run them) ----

// requireSystemSSH guards the e2e tests below: Interactive execs the real ssh
// binary, which CI/container environments often do not ship — those runs are
// skipped, not failed. HOME is pointed at a fresh temp dir so a developer's
// ~/.ssh/config cannot inject options (ProxyJump, IdentityFile overrides, …)
// into the test run.
func requireSystemSSH(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("ssh"); err != nil {
		t.Skip("system ssh binary not found in PATH; skipping Interactive e2e tests")
	}
	t.Setenv("HOME", t.TempDir())
}

// interactiveClient dials the in-process server so the Client carries a fully
// resolved cfg (host/port/key path) that Interactive execs ssh with. The
// pooled connection itself is not used by Interactive, but Dial also validates
// the server is reachable — keepalive stays off for determinism.
func interactiveClient(t *testing.T, srv *sshtest.Server) *Client {
	t.Helper()
	c := dialServer(t, srv)
	t.Cleanup(func() { _ = c.Close() })
	return c
}

// TestInteractiveRelaysRemoteExitStatus covers the md.sh `exit $?`-style flow
// end to end: `ssh -T` against the in-process server must relay the remote
// exit code as *ExitError (zero stays nil), exactly like md.sh reads `$?` from
// the ssh process.
func TestInteractiveRelaysRemoteExitStatus(t *testing.T) {
	requireSystemSSH(t)
	srv := sshtest.NewServer(t)
	c := interactiveClient(t, srv)

	cases := []struct {
		name  string
		shell string
		want  int
	}{
		{name: "zero exit", shell: "exit 0", want: 0},
		{name: "exit three", shell: "exit 3", want: 3},
		{name: "false", shell: "false", want: 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer cancel()
			err := c.Interactive(ctx, InteractiveRequest{Shell: tc.shell, ForceNoTTY: true})
			if tc.want == 0 {
				if err != nil {
					t.Fatalf("Interactive(%q) = %v, want nil for a clean exit", tc.shell, err)
				}
				return
			}
			var exitErr *ExitError
			if !errors.As(err, &exitErr) {
				t.Fatalf("Interactive(%q) = %v, want *ExitError{Code:%d}", tc.shell, err, tc.want)
			}
			if exitErr.Code != tc.want {
				t.Errorf("ExitError.Code = %d, want %d", exitErr.Code, tc.want)
			}
		})
	}
}

// TestInteractiveServerClosedIsConnFailed: once the server is gone, system ssh
// exits 255 ("ssh could not establish/keep the session") and Interactive must
// classify that as ErrConnFailed rather than a remote exit code.
func TestInteractiveServerClosedIsConnFailed(t *testing.T) {
	requireSystemSSH(t)
	srv := sshtest.NewServer(t)
	c := interactiveClient(t, srv)
	srv.Close() // nothing listens on the port anymore; ssh will exit 255

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	err := c.Interactive(ctx, InteractiveRequest{Shell: "exit 0", ForceNoTTY: true})
	if !errors.Is(err, ErrConnFailed) {
		t.Fatalf("Interactive after server close = %v, want ErrConnFailed (ssh 255 mapping)", err)
	}
}

// TestInteractiveContextCancelKillsSSH: cancelling the caller context must kill
// the local ssh child and return promptly with context.Canceled — the ^C-on-
// `ssh -t` semantics for an interactive session.
func TestInteractiveContextCancelKillsSSH(t *testing.T) {
	requireSystemSSH(t)
	srv := sshtest.NewServer(t)
	c := interactiveClient(t, srv)

	ctx, cancel := context.WithCancel(context.Background())
	errCh := make(chan error, 1)
	go func() {
		errCh <- c.Interactive(ctx, InteractiveRequest{Shell: "sleep 30", ForceNoTTY: true})
	}()
	time.Sleep(300 * time.Millisecond) // let ssh establish and start the remote command
	cancel()

	select {
	case err := <-errCh:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Interactive error = %v, want context.Canceled", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("Interactive did not return after context cancel")
	}
}
