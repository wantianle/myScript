package svc

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"mdrive/md/internal/config"
	"mdrive/md/internal/logx"
)

// discardLog returns a Logger that writes to a buffer (tests assert on it).
func bufferLog() (*logx.Logger, *bytes.Buffer) {
	buf := &bytes.Buffer{}
	return logx.NewWithWriter(buf), buf
}

func TestResolveSOCArg(t *testing.T) {
	tests := []struct {
		in   string
		want string
		ok   bool
	}{
		{"", "both", true},
		{"soc1", "soc1", true},
		{"1", "soc1", true},
		{"soc2", "soc2", true},
		{"2", "soc2", true},
		{"both", "", false},
		{"soc3", "", false},
		{"abc", "", false},
	}
	for _, tt := range tests {
		got, err := ResolveSOCArg(tt.in)
		if tt.ok != (err == nil) {
			t.Errorf("ResolveSOCArg(%q) err = %v, want ok=%v", tt.in, err, tt.ok)
		}
		if tt.ok && got != tt.want {
			t.Errorf("ResolveSOCArg(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}

// fakeShell records commands and returns canned ExecOut. It satisfies Shell.
type fakeShell struct {
	commands    []string
	execOuts    map[string]ExecOut
	interactive []string
}

func (f *fakeShell) Exec(_ context.Context, cmd string) (ExecOut, error) {
	f.commands = append(f.commands, cmd)
	if out, ok := f.execOuts[cmd]; ok {
		return out, nil
	}
	return ExecOut{}, nil
}

func (f *fakeShell) Stream(_ context.Context, cmd string) (<-chan Chunk, <-chan error) {
	f.commands = append(f.commands, cmd)
	return nil, nil
}

func (f *fakeShell) Interactive(_ context.Context, cmd string) error {
	f.interactive = append(f.interactive, cmd)
	return nil
}

func (f *fakeShell) Close() error { return nil }

func TestManageRejectsBadAction(t *testing.T) {
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return &fakeShell{}, nil
	})
	if err := svc.Manage(context.Background(), "frobnicate", "soc1"); err == nil {
		t.Fatal("Manage should reject a non-whitelisted action")
	}
}

func TestManageWhitelistAndTargets(t *testing.T) {
	fs := &fakeShell{}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})

	// soc1 start: should issue systemctl start locally, no stop-polling.
	if err := svc.Manage(context.Background(), "start", "soc1"); err != nil {
		t.Fatalf("Manage(soc1,start) err = %v", err)
	}
	found := false
	for _, c := range fs.commands {
		if strings.Contains(c, "sudo systemctl start mdrive.service") {
			found = true
		}
	}
	if !found {
		t.Errorf("soc1 start did not run systemctl start; commands=%v", fs.commands)
	}

	// soc2 stop: should issue timeout-15 sudo systemctl stop + a stop-poll probe.
	fs.commands = nil
	if err := svc.Manage(context.Background(), "stop", "soc2"); err != nil {
		t.Fatalf("Manage(soc2,stop) err = %v", err)
	}
	var sawStop, sawPoll bool
	for _, c := range fs.commands {
		if strings.Contains(c, "timeout 15 sudo systemctl stop mdrive.service") {
			sawStop = true
		}
		if strings.Contains(c, "for i in $(seq 1 12)") {
			sawPoll = true
		}
	}
	if !sawStop || !sawPoll {
		t.Errorf("soc2 stop missing stop/poll; commands=%v", fs.commands)
	}
}

func TestManageBothRunsBothSocs(t *testing.T) {
	fs := &fakeShell{}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.Manage(context.Background(), "restart", "both"); err != nil {
		t.Fatalf("Manage(both) err = %v", err)
	}
	if len(fs.commands) == 0 {
		t.Fatal("both should have issued commands")
	}
	// Hmm — both uses "soc1" and "soc2"; a simple count sanity check.
	if len(fs.commands) < 4 {
		t.Errorf("expected at least 4 commands for both (2 socs, each with action + check), got %d", len(fs.commands))
	}
}

func TestCheckSoc2SshTransportFailure(t *testing.T) {
	// soc2 Exec returns error (transport 255) -> Check should return an error.
	fs := &fakeShell{execOuts: map[string]ExecOut{}}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return failingExecShell{Shell: fs}, nil
	})
	if err := svc.Check(context.Background(), "soc2"); err == nil {
		t.Fatal("Check(soc2) with transport failure should return an error")
	}
}

// failingExecShell wraps a Shell and forces every Exec to error (simulating a
// dead ssh connection / 255).
type failingExecShell struct{ Shell }

func (f failingExecShell) Exec(ctx context.Context, cmd string) (ExecOut, error) {
	return ExecOut{}, context.DeadlineExceeded
}

func TestRecorderOffProceedsWithoutDisk(t *testing.T) {
	fs := &fakeShell{
		// mountpoint fails (disk not mounted)
		execOuts: map[string]ExecOut{
			"timeout 2 mountpoint -q /media/data": {Code: 1},
		},
	}
	log, buf := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.Recorder(context.Background(), "off"); err != nil {
		t.Fatalf("Recorder(off) should proceed despite unmounted disk, err = %v", err)
	}
	if !strings.Contains(buf.String(), "硬盘未挂载") {
		t.Errorf("off path should log the unmounted warning, got %q", buf.String())
	}
}

func TestRecorderOnRefusesWithoutDisk(t *testing.T) {
	fs := &fakeShell{
		execOuts: map[string]ExecOut{
			"timeout 2 mountpoint -q /media/data": {Code: 1},
		},
	}
	log, buf := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.Recorder(context.Background(), "on"); err == nil {
		t.Fatal("Recorder(on) must refuse when the disk is not mounted")
	}
	if !strings.Contains(buf.String(), "拒绝启动 Recorder") {
		t.Errorf("on path should log the refusal, got %q", buf.String())
	}
}

func TestRecorderOnWithDiskStarts(t *testing.T) {
	fs := &fakeShell{
		execOuts: map[string]ExecOut{
			"timeout 2 mountpoint -q /media/data":                                   {Code: 0},
			"df -BG /media/data 2>/dev/null | awk 'NR==2 {print \\$4}' | tr -d 'G'": {Stdout: "500\n"},
			"sudo supervisorctl start Recorder 2>/dev/null":                         {Code: 0},
		},
	}
	log, buf := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.Recorder(context.Background(), "on"); err != nil {
		t.Fatalf("Recorder(on) with mounted disk err = %v", err)
	}
	if !strings.Contains(buf.String(), "Recorder 已启动") {
		t.Errorf("on path should log started, got %q", buf.String())
	}
}

func TestChannelSoc2BuildsEnvPrefix(t *testing.T) {
	fs := &fakeShell{}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.Channel(context.Background(), "soc2"); err != nil {
		t.Fatalf("Channel(soc2) err = %v", err)
	}
	if len(fs.interactive) != 1 {
		t.Fatalf("expected 1 interactive call, got %d", len(fs.interactive))
	}
	got := fs.interactive[0]
	if !strings.Contains(got, "export MDRIVE_ROOT_DIR=/mdrive") ||
		!strings.Contains(got, "dtop") {
		t.Errorf("soc2 channel command should carry env prefix + dtop, got %q", got)
	}
}

func TestChannelBadSoc(t *testing.T) {
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return &fakeShell{}, nil
	})
	if err := svc.Channel(context.Background(), "soc3"); err == nil {
		t.Fatal("Channel with invalid soc should error")
	}
}
