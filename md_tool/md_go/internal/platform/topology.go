package platform

import (
	"mdrive/md/internal/config"
)

// EndpointKind is how a logical soc target is executed.
type EndpointKind string

const (
	// Local executes on the current host (the md process's own soc).
	Local EndpointKind = "local"
	// SSH executes remotely by dialing a host.
	SSH EndpointKind = "ssh"
)

// Endpoint is a resolved execution target for a logical soc.
type Endpoint struct {
	Kind EndpointKind
	Host string
	User string
}

// Topology resolves a logical soc target into a concrete Endpoint given the
// current host identity. It backs the dual-soc routing matrix that replaces
// svc's hard-coded "soc2 → ssh, else local" assumption (P2).
//
// The routing matrix (user-approved, mr.sh/mdrive4 dual-soc):
//
//	host=soc1: soc1→local, soc2→ssh(SOC2IP)
//	host=soc2: soc2→local, soc1→ssh(SOC1IP)
//	host=external: soc1→ssh(SOC1IP), soc2→ssh(SOC2IP)
//
// A host that is itself a soc never sshes back to itself (the direct fix for
// "md start on soc2 would have ssh'd back to soc2").
type Topology struct {
	cfg    config.Config
	SelfID config.SOCID
}

// EndpointFor returns the execution endpoint for a logical soc (soc1|soc2)
// from the current host's perspective. Unknown targets resolve to ssh to the
// matching SOC1IP/SOC2IP (safe default).
func (t Topology) EndpointFor(soc string) Endpoint {
	switch t.SelfID {
	case config.SOC1:
		if soc == "soc2" {
			return Endpoint{Kind: SSH, Host: t.cfg.SOC2IP}
		}
		return Endpoint{Kind: Local, Host: ""}
	case config.SOC2:
		if soc == "soc1" {
			return Endpoint{Kind: SSH, Host: t.cfg.SOC1IP}
		}
		return Endpoint{Kind: Local, Host: ""}
	default: // external
		host := t.cfg.SOC2IP
		if soc == "soc1" {
			host = t.cfg.SOC1IP
		}
		return Endpoint{Kind: SSH, Host: host}
	}
}

// IsSelf reports whether soc is this host's own identity (so business logic can
// warn instead of ssh-ing back to itself).
func (t Topology) IsSelf(soc string) bool {
	return (t.SelfID == config.SOC1 && soc == "soc1") ||
		(t.SelfID == config.SOC2 && soc == "soc2")
}

// NewTopology builds a Topology from config + detected identity.
func NewTopology(cfg config.Config, selfID config.SOCID) Topology {
	return Topology{cfg: cfg, SelfID: selfID}
}
