package svc

import (
	"context"
	"testing"

	"mdrive/md/internal/config"
)

// statesShell returns a Shell whose Exec answers the is-active probe with a
// configurable exit code per soc name (the command payload is shared, so we
// tag the reply by the command string). We drive it through a fake execOuts map
// so `systemctl is-active --quiet mdrive.service` returns the wanted code.
func TestCheckStatesBothAggregates(t *testing.T) {
	fs := &fakeShell{execOuts: map[string]ExecOut{
		"systemctl is-active --quiet mdrive.service": {Code: 0},
	}}
	log, _ := bufferLog()
	s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	states, err := s.CheckStates(context.Background(), "both")
	if err != nil {
		t.Fatalf("both healthy → err = %v, want nil", err)
	}
	if len(states) != 2 || states[0].SOC != "soc1" || states[1].SOC != "soc2" {
		t.Errorf("states = %+v, want [soc1 soc2]", states)
	}
	if states[0].State != "Running" || states[1].State != "Running" {
		t.Errorf("both should be Running: %+v", states)
	}
}

func TestCheckStatesAnyFailNonZero(t *testing.T) {
	// soc1 healthy, but soc2's probe returns non-zero => check must fail.
	fs := &fakeShell{execOuts: map[string]ExecOut{
		"systemctl is-active --quiet mdrive.service": {Code: 3}, // non-zero
	}}
	log, _ := bufferLog()
	s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	states, err := s.CheckStates(context.Background(), "both")
	if err == nil {
		t.Fatal("expected non-nil error when a soc is down")
	}
	// The structured states are still returned so the caller can render them.
	for _, st := range states {
		if st.State == "Running" {
			t.Errorf("a down soc must not report Running: %+v", states)
		}
	}
}

func TestCheckStatesSingleSoc(t *testing.T) {
	fs := &fakeShell{execOuts: map[string]ExecOut{
		"systemctl is-active --quiet mdrive.service": {Code: 0},
	}}
	log, _ := bufferLog()
	s := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})
	states, err := s.CheckStates(context.Background(), "soc2")
	if err != nil {
		t.Fatalf("soc2 healthy → err = %v", err)
	}
	if len(states) != 1 || states[0].SOC != "soc2" {
		t.Errorf("states = %+v, want [soc2]", states)
	}
}
