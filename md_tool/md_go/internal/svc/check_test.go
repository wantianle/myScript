package svc

import (
	"context"
	"strings"
	"testing"

	"mdrive/md/internal/config"
)

// TestPreCheckSoc2NetworkHardGate: SOC2 unreachable should abort early with an
// error (md.sh returns 1 immediately).
func TestPreCheckSoc2NetworkHardGate(t *testing.T) {
	// fakeShell returns an error on every Exec -> models an unreachable soc2.
	failing := &errShell{err: context.DeadlineExceeded}
	log, buf := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return failing, nil
	})
	if err := svc.PreCheck(context.Background()); err == nil {
		t.Fatal("PreCheck should error when soc2 is unreachable")
	}
	if !strings.Contains(buf.String(), "soc2 供电/网线") {
		t.Errorf("expected a soc2-recovery hint, got %q", buf.String())
	}
}

// TestPreCheckPass: all segments healthy -> nil.
func TestPreCheckPass(t *testing.T) {
	fs := &fakeShell{
		execOuts: map[string]ExecOut{
			"exit": {Code: 0},
			// network server ping ok
			"ping -c 1 -W 1 ad.minieye.tech": {Code: 0},
			// root disk < 85%
			"df -h / 2>/dev/null":              {Stdout: dfLine("/", "40")},
			"df -h /mdrive/.cache 2>/dev/null": {Stdout: dfLine("/mdrive/.cache", "30")},
			// external disk mount + content ok
			"mountpoint -q /media/data":                          {Code: 0},
			"timeout 2 stat -t /media/data/data >/dev/null 2>&1": {Code: 0},
			"cat /proc/mounts":                                   {Stdout: ""},
			"df -h /media/data 2>/dev/null":                      {Stdout: dfLine("/media/data", "50")},
			"df -BG /mdrive/.cache 2>/dev/null":                  {Stdout: dfBGLine("/mdrive/.cache", "100")},
			// service state
			"systemctl is-active --quiet mdrive.service": {Code: 0},
			// time sync (server reachable, same epoch)
			"date +%s":                  {Stdout: "1700000000\n"},
			"date +'%Y-%m-%d %H:%M:%S'": {Stdout: "2023-11-14 22:13:20\n"},
		},
	}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	if err := svc.PreCheck(context.Background()); err != nil {
		t.Fatalf("PreCheck on healthy env err = %v", err)
	}
}

// errShell models a target whose commands all fail (unreachable).
type errShell struct{ err error }

func (e *errShell) Exec(context.Context, string) (ExecOut, error) { return ExecOut{}, e.err }
func (e *errShell) Stream(context.Context, string) (<-chan Chunk, <-chan error) {
	return nil, nil
}
func (e *errShell) Interactive(context.Context, string) error { return e.err }
func (e *errShell) Close() error                              { return nil }

// dfLine builds a `df -h` single-row output with the given mount and %used.
func dfLine(mount, pct string) string {
	return "Filesystem      Size  Used Avail Use% Mounted on\n/dev/x 100G " + pct + "G 50G " + pct + "% " + mount + "\n"
}

// dfBGLine builds a `df -BG` single-row output with the given mount and GB.
func dfBGLine(mount, gb string) string {
	return "Filesystem     1B-blocks  Used Available Use% Mounted on\n/dev/x 100G 10G " + gb + "G 10% " + mount + "\n"
}
