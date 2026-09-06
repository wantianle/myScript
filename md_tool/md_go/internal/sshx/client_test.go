package sshx

import (
	"context"
	"errors"
	"net"
	"strings"
	"testing"
	"time"
)

// TestResolveConfigDefaults verifies the md.sh SSH_OPTS-aligned defaults are
// applied to a mostly-zero ClientConfig: md.sh:24-32 (ConnectTimeout=2,
// ServerAliveInterval=2, ServerAliveCountMax=2, StrictHostKeyChecking=no,
// UserKnownHostsFile=/dev/null, -i $HOME/.ssh/id_ed25519).
func TestResolveConfigDefaults(t *testing.T) {
	cfg, err := resolveConfig(ClientConfig{Host: "192.168.10.3"})
	if err != nil {
		t.Fatalf("resolveConfig: %v", err)
	}
	if cfg.User == "" {
		t.Error("default user must not be empty (md.sh relies on $USER)")
	}
	if cfg.Port != 22 {
		t.Errorf("default port = %d, want 22", cfg.Port)
	}
	if !strings.HasSuffix(cfg.KeyPath, "/.ssh/id_ed25519") {
		t.Errorf("default key path = %q, want ~/.ssh/id_ed25519", cfg.KeyPath)
	}
	if cfg.DialTimeout != 2*time.Second {
		t.Errorf("DialTimeout = %v, want 2s (ConnectTimeout=2)", cfg.DialTimeout)
	}
	if cfg.HandshakeTimeout != 5*time.Second {
		t.Errorf("HandshakeTimeout = %v, want 5s", cfg.HandshakeTimeout)
	}
	if cfg.KeepAliveInterval != 2*time.Second {
		t.Errorf("KeepAliveInterval = %v, want 2s (ServerAliveInterval=2)", cfg.KeepAliveInterval)
	}
	if cfg.KeepAliveCountMax != 2 {
		t.Errorf("KeepAliveCountMax = %d, want 2 (ServerAliveCountMax=2)", cfg.KeepAliveCountMax)
	}
	if cfg.HostKeyCallback == nil {
		t.Error("HostKeyCallback must default to InsecureIgnoreHostKey (StrictHostKeyChecking=no)")
	}
}

func TestResolveConfigKeepsOverrides(t *testing.T) {
	cfg, err := resolveConfig(ClientConfig{
		Host:              "h",
		User:              "mini",
		Port:              2222,
		KeyPath:           "/custom/key",
		DialTimeout:       7 * time.Second,
		HandshakeTimeout:  9 * time.Second,
		KeepAliveInterval: 5 * time.Second,
		KeepAliveCountMax: 7,
	})
	if err != nil {
		t.Fatalf("resolveConfig: %v", err)
	}
	if cfg.User != "mini" || cfg.Port != 2222 || cfg.KeyPath != "/custom/key" ||
		cfg.DialTimeout != 7*time.Second || cfg.KeepAliveInterval != 5*time.Second ||
		cfg.KeepAliveCountMax != 7 {
		t.Errorf("overrides were clobbered: %+v", cfg)
	}
}

// A negative KeepAliveInterval is the documented escape hatch to disable the
// keepalive goroutine (md.sh always keeps it on; tests use this).
func TestResolveConfigNegativeIntervalStaysDisabled(t *testing.T) {
	cfg, err := resolveConfig(ClientConfig{Host: "h", KeepAliveInterval: -1})
	if err != nil {
		t.Fatalf("resolveConfig: %v", err)
	}
	if cfg.KeepAliveInterval >= 0 {
		t.Errorf("KeepAliveInterval = %v, want negative (disabled)", cfg.KeepAliveInterval)
	}
}

func TestResolveConfigRejectsEmptyHost(t *testing.T) {
	if _, err := resolveConfig(ClientConfig{}); !errors.Is(err, ErrConnFailed) {
		t.Fatalf("empty host error = %v, want ErrConnFailed", err)
	}
}

// TestDialConnectionRefused exercises the ErrConnFailed classification for a
// TCP dial that goes nowhere (the ssh -n failure a Bash script would see as
// "Connection refused").
func TestDialConnectionRefused(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	_ = ln.Close() // now nothing listens on addr

	host, portStr, _ := net.SplitHostPort(addr)
	_, err = Dial(context.Background(), ClientConfig{
		Host: host, Port: atoi(portStr), User: "test",
		KeyPath: mustWriteTestKey(t),
	})
	if !errors.Is(err, ErrConnFailed) {
		t.Fatalf("Dial to closed port = %v, want ErrConnFailed", err)
	}
}

func atoi(s string) int {
	var n int
	for i := 0; i < len(s); i++ {
		n = n*10 + int(s[i]-'0')
	}
	return n
}
