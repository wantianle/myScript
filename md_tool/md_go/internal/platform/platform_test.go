package platform

import (
	"context"
	"testing"

	"mdrive/md/internal/config"
)

// fakeRun returns a fixed stdout for any command (identity probes use only the
// `ip -4 addr show mgbe3_0` output). A nil stdout signals "command failed".
func fakeRun(out string) runFunc {
	return func(ctx context.Context, args ...string) (string, error) {
		if out == "" {
			return "", context.DeadlineExceeded
		}
		return out, nil
	}
}

const soc1AddrOut = "mgbe3_0: inet 172.168.16.101/24"
const soc2AddrOut = "mgbe3_0: inet 192.168.1.101/24"
const noneAddrOut = "mgbe3_0: inet 10.0.0.1/24"

func TestDetectIdentityOverride(t *testing.T) {
	cases := []struct {
		name string
		id   config.SOCID
		want config.SOCID
	}{
		{"soc1", config.SOC1, config.SOC1},
		{"soc2", config.SOC2, config.SOC2},
		{"external", config.SOCExternal, config.SOCExternal},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			cfg := config.Default()
			cfg.SOCID = c.id
			if got := DetectIdentity(context.Background(), cfg); got != c.want {
				t.Errorf("DetectIdentity override = %v, want %v", got, c.want)
			}
		})
	}
}

func TestDetectIdentityByAddress(t *testing.T) {
	cases := []struct {
		name string
		out  string
		want config.SOCID
	}{
		{"soc1-172.168.16.101", soc1AddrOut, config.SOC1},
		{"soc1-192.168.1.100", "mgbe3_0: inet 192.168.1.100/24", config.SOC1},
		{"soc2-172.168.16.103", "mgbe3_0: inet 172.168.16.103/24", config.SOC2},
		{"soc2-192.168.1.101", soc2AddrOut, config.SOC2},
		{"neither", noneAddrOut, config.SOCExternal},
		{"probe-failed", "", config.SOCExternal},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			cfg := config.Default() // empty SOCID → detect by address
			cfg.SOCID = ""
			got := detectByAddress(context.Background(), cfg, fakeRun(c.out))
			if got != c.want {
				t.Errorf("detectByAddress(%q) = %v, want %v", c.out, got, c.want)
			}
		})
	}
}

func TestTopologyRoutingMatrix(t *testing.T) {
	cfg := config.Default()
	cfg.SOC1IP = "10.0.0.2"
	cfg.SOC2IP = "10.0.0.3"

	// We test the resolved endpoint kind+host against the approved matrix.
	check := func(t *testing.T, self, target config.SOCID, wantKind EndpointKind, wantHost string) {
		t.Helper()
		tp := NewTopology(cfg, self)
		got := tp.EndpointFor(string(target))
		if got.Kind != wantKind || got.Host != wantHost {
			t.Errorf("self=%v target=%v → {kind:%v host:%v}, want {kind:%v host:%v}",
				self, target, got.Kind, got.Host, wantKind, wantHost)
		}
	}

	t.Run("on-soc1", func(t *testing.T) {
		check(t, config.SOC1, config.SOC1, Local, "") // never ssh to self
		check(t, config.SOC1, config.SOC2, SSH, "10.0.0.3")
	})
	t.Run("on-soc2", func(t *testing.T) {
		check(t, config.SOC2, config.SOC2, Local, "") // never ssh to self
		check(t, config.SOC2, config.SOC1, SSH, "10.0.0.2")
	})
	t.Run("external", func(t *testing.T) {
		check(t, config.SOCExternal, config.SOC1, SSH, "10.0.0.2")
		check(t, config.SOCExternal, config.SOC2, SSH, "10.0.0.3")
	})
}

func TestTopologyIsSelf(t *testing.T) {
	cfg := config.Default()
	soc1tp := NewTopology(cfg, config.SOC1)
	if !soc1tp.IsSelf("soc1") || soc1tp.IsSelf("soc2") {
		t.Errorf("soc1-topology IsSelf wrong: soc1→%v soc2→%v", soc1tp.IsSelf("soc1"), soc1tp.IsSelf("soc2"))
	}
	soc2tp := NewTopology(cfg, config.SOC2)
	if !soc2tp.IsSelf("soc2") || soc2tp.IsSelf("soc1") {
		t.Errorf("soc2-topology IsSelf wrong: soc2→%v soc1→%v", soc2tp.IsSelf("soc2"), soc2tp.IsSelf("soc1"))
	}
}
