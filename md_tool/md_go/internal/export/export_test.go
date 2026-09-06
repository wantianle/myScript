package export

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"mdrive/md/internal/transfer"
)

func TestIsPrivateIP(t *testing.T) {
	cases := map[string]bool{
		"10.1.2.3":     true,
		"192.168.1.5":  true,
		"172.16.0.1":   true,
		"172.31.255.1": true,
		"172.32.0.1":   false,
		"172.15.0.1":   false,
		"8.8.8.8":      false,
		"":             false,
	}
	for ip, want := range cases {
		if got := IsPrivateIP(ip); got != want {
			t.Errorf("IsPrivateIP(%q) = %v, want %v", ip, got, want)
		}
	}
}

func TestIsLocalhostIP(t *testing.T) {
	for _, ip := range []string{"127.0.0.1", "localhost", "::1"} {
		if !IsLocalhostIP(ip) {
			t.Errorf("IsLocalhostIP(%q) = false, want true", ip)
		}
	}
	if IsLocalhostIP("192.168.1.1") {
		t.Error("192.168.1.1 is not loopback")
	}
}

func TestResolveTargetLAN(t *testing.T) {
	tgt, err := ResolveTarget("192.168.1.5 30000 192.168.1.1 22", nil, "")
	if err != nil {
		t.Fatal(err)
	}
	if tgt.IP != "192.168.1.5" || tgt.Port != "22" || tgt.Source != "lan" {
		t.Errorf("LAN target = %+v", tgt)
	}
}

func TestResolveTargetLanRejectsLocalhostSrc(t *testing.T) {
	// A loopback source must NOT be treated as a LAN direct connection.
	if _, err := ResolveTarget("127.0.0.1 1 127.0.0.1 22", []string{"2222"}, ""); err != nil {
		t.Fatalf("expected tunnel fallback, got err %v", err)
	}
}

func TestResolveTargetSingleTunnel(t *testing.T) {
	tgt, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", []string{"2222"}, "")
	if err != nil {
		t.Fatal(err)
	}
	if tgt.IP != "127.0.0.1" || tgt.Port != "2222" || tgt.Source != "tunnel" {
		t.Errorf("tunnel target = %+v", tgt)
	}
}

func TestResolveTargetNoTunnel(t *testing.T) {
	if _, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", nil, ""); err != ErrNoTunnel {
		t.Errorf("expected ErrNoTunnel, got %v", err)
	}
}

func TestResolveTargetAmbiguous(t *testing.T) {
	if _, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", []string{"2222", "3333"}, ""); err != ErrAmbiguous {
		t.Errorf("expected ErrAmbiguous, got %v", err)
	}
	// With an explicit port, ambiguity is resolved.
	tgt, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", []string{"2222", "3333"}, "3333")
	if err != nil {
		t.Fatal(err)
	}
	if tgt.Port != "3333" {
		t.Errorf("port = %s, want 3333", tgt.Port)
	}
}

func TestResolveTargetInvalidPort(t *testing.T) {
	if _, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", nil, "70000"); err == nil {
		t.Error("expected error for out-of-range port")
	}
	if _, err := ResolveTarget("ad.minieye.tech 22 10.0.0.1 22", []string{"abc"}, ""); err == nil {
		t.Error("expected error for non-numeric port")
	}
}

func TestScanDataRoot(t *testing.T) {
	root := t.TempDir()
	mk := func(p string) {
		if err := os.MkdirAll(filepath.Join(root, p), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	wf := func(p, content string) {
		if err := os.WriteFile(filepath.Join(root, p), []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	mk("bag")
	mk("log")
	mk("log/sub")
	mk(".hidden")
	wf("bag/001.bag", "x")
	wf("log/run.log", "y")
	wf("log/sub/deep.log", "z")
	wf(".hidden/secret", "s")
	wf("root.log", "r")

	got, err := ScanDataRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	// Hidden paths excluded; depth <= 3.
	want := []string{"bag", "bag/001.bag", "log", "log/run.log", "log/sub", "log/sub/deep.log", "root.log"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ScanDataRoot =\n%v\nwant\n%v", got, want)
	}
}

func TestExportOffline(t *testing.T) {
	root := t.TempDir()
	dstRoot := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "bag"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "bag", "001.bag"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "root.log"), []byte("r"), 0o644); err != nil {
		t.Fatal(err)
	}

	tr := transfer.NewLocalDirTransport(dstRoot)
	var logs []string
	opts := PushOptions{
		DataRoot:  root,
		Dest:      "/media/mdrive_export/0101_0000",
		Transport: tr,
		Log:       func(level, msg string) { logs = append(logs, level+":"+msg) },
	}
	failed, err := Export(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	if failed != 0 {
		t.Errorf("Export failed count = %d", failed)
	}
	// Validate the pushed tree mirrors the source.
	for _, f := range []string{"bag/001.bag", "root.log"} {
		if _, err := os.Stat(filepath.Join(dstRoot, "media", "mdrive_export", "0101_0000", filepath.FromSlash(f))); err != nil {
			t.Errorf("expected pushed %s: %v", f, err)
		}
	}
}

func TestExportSelectsOnlyPicked(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "a.log"), []byte("a"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "b.log"), []byte("b"), 0o644); err != nil {
		t.Fatal(err)
	}
	dst := t.TempDir()
	tr := transfer.NewLocalDirTransport(dst)
	opts := PushOptions{
		DataRoot:  root,
		Dest:      "/media/export",
		Transport: tr,
		SelectFiles: func(items []string) []string {
			for _, i := range items {
				if i == "a.log" {
					return []string{i}
				}
			}
			return nil
		},
	}
	failed, err := Export(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	if failed != 0 {
		t.Errorf("failed = %d", failed)
	}
	if _, err := os.Stat(filepath.Join(dst, "media", "export", "a.log")); err != nil {
		t.Errorf("a.log not pushed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dst, "media", "export", "b.log")); !os.IsNotExist(err) {
		t.Errorf("b.log should not have been pushed (err=%v)", err)
	}
}
