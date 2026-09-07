package svc

import (
	"context"
	"os"
	"testing"

	"mdrive/md/internal/config"
)

func TestResolveChannelToolFallback(t *testing.T) {
	probeCmd := "command -v dtop || command -v cyber_monitor"
	cases := []struct {
		name string
		out  string
		want string
	}{
		{"dtop-present", "/usr/bin/dtop", "dtop"},
		{"cyber-monitor-only", "/usr/bin/cyber_monitor", "cyber_monitor"},
		{"empty-probe", "", "dtop"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			fs := &fakeShell{execOuts: map[string]ExecOut{probeCmd: {Stdout: c.out}}}
			log, _ := bufferLog()
			s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
				return fs, nil
			})
			if got := s.resolveChannelTool(context.Background(), fs, "soc1"); got != c.want {
				t.Errorf("resolveChannelTool = %q, want %q", got, c.want)
			}
		})
	}
}

func TestResolveChannelToolEnvOverride(t *testing.T) {
	t.Setenv("MD_CHANNEL_TOOL", "cyber_monitor")
	log, _ := bufferLog()
	s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return &fakeShell{}, nil
	})
	// The env override should short-circuit the probe entirely.
	if got := s.resolveChannelTool(context.Background(), &fakeShell{}, "soc1"); got != "cyber_monitor" {
		t.Errorf("env override = %q, want cyber_monitor", got)
	}
}

func TestResolveSOCChannel(t *testing.T) {
	cases := map[string]string{
		"": "soc1", "soc1": "soc1", "1": "soc1",
		"soc2": "soc2", "2": "soc2",
	}
	for in, want := range cases {
		got, err := ResolveSOC(in, "soc1", false)
		if err != nil {
			t.Errorf("ResolveSOC(%q) err = %v", in, err)
		}
		if got != want {
			t.Errorf("ResolveSOC(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestChannelInteractiveCmd(t *testing.T) {
	// soc1 (no env prefix) should launch "dtop <args>"; we verify via the
	// fakeShell's captured interactive command.
	fs := &fakeShell{execOuts: map[string]ExecOut{
		"command -v dtop || command -v cyber_monitor": {Stdout: "/usr/bin/dtop"},
	}}
	log, _ := bufferLog()
	s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := s.Channel(context.Background(), "soc1", []string{"-h"}); err != nil {
		t.Fatalf("Channel: %v", err)
	}
	if len(fs.interactive) != 1 || fs.interactive[0] != "dtop -h" {
		t.Errorf("interactive cmd = %v, want [dtop -h]", fs.interactive)
	}
}

func BenchmarkResolveChannelTool(b *testing.B) {
	_ = os.Getenv("MD_CHANNEL_TOOL")
}
