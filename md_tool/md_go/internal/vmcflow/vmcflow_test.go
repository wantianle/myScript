package vmcflow

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"mdrive/md/internal/logx"
	"mdrive/md/internal/vmc"
)

// fakeRun returns a runFunc backed by a map of "name arg1 arg2..." → stdout.
func fakeRun(resp map[string]string) runFunc {
	return func(ctx context.Context, name string, args ...string) (string, string, int, error) {
		key := strings.Join(append([]string{name}, args...), " ")
		if out, ok := resp[key]; ok {
			return out, "", 0, nil
		}
		return "", "", 1, nil
	}
}

func vmcNew(r runFunc) *VMC {
	return &VMC{Cfg: Cfg{}, Runner: r, Log: newTestLog()}
}

func newTestLog() *logx.Logger {
	return logx.NewWithWriter(&bytes.Buffer{})
}

func writeTempRemotes(t *testing.T, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), ".md_remotes")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestSplitRemote(t *testing.T) {
	tests := []struct {
		line string
		want RemoteRow
	}{
		{"dev main orin", RemoteRow{Name: "dev", Branch: "main", Platform: "orin"}},
		{"beta - ", RemoteRow{Name: "beta", Branch: "-", Platform: ""}},
		{"gamma stable", RemoteRow{Name: "gamma", Branch: "stable", Platform: ""}},
	}
	for _, tt := range tests {
		if got := splitRemote(tt.line); got != tt.want {
			t.Errorf("splitRemote(%q) = %+v, want %+v", tt.line, got, tt.want)
		}
	}
}

func TestCheckUpdatesScansRemotes(t *testing.T) {
	r := fakeRun(map[string]string{
		"vmc list":              "mdrive 1.0.0\nmdrive_conf 2.0.0\n",
		"vmc fsearch -n mdrive": "name: mdrive, version: 1.0.0, platform: orin\n",
	})
	v := &VMC{Runner: r, Cfg: Cfg{RemotesPath: writeTempRemotes(t, "mdrive - orin\n")}, Log: newTestLog()}
	items, err := v.CheckUpdates(context.Background())
	if err != nil {
		t.Fatalf("CheckUpdates err = %v", err)
	}
	if len(items) != 1 || items[0].Pkg != "mdrive" || items[0].Latest != "1.0.0" {
		t.Fatalf("CheckUpdates = %+v", items)
	}
}

func TestFinstallResolvesPkgFromVersion(t *testing.T) {
	// fsearch -v 1.1.2 yields mdrive_cve before mdrive_dep; SelectPackageByVersion
	// picks the exact-version match (first record). Install then runs.
	installed := false
	r := func(ctx context.Context, name string, args ...string) (string, string, int, error) {
		if name == "vmc" && len(args) >= 1 && args[0] == "fsearch" {
			return "name: mdrive_cve, version: 1.1.2, platform: orin\n", "", 0, nil
		}
		if name == "vmc" && len(args) >= 1 && args[0] == "install" {
			installed = true
			return "", "", 0, nil
		}
		if name == "vmc" && len(args) >= 1 && args[0] == "list" {
			return "mdrive_cve 1.1.2\n", "", 0, nil
		}
		return "", "", 1, nil
	}
	v := vmcNew(r)
	if err := v.Finstall(context.Background(), "1.1.2", ""); err != nil {
		t.Fatalf("Finstall err = %v", err)
	}
	if !installed {
		t.Fatal("expected vmc install to run after pkg resolution")
	}
}

func TestRenderCandidatesSortsDescending(t *testing.T) {
	recs := []vmc.Record{
		{Name: "a", Version: "1.3.0"},
		{Name: "b", Version: "1.1.2"},
		{Name: "c", Version: "2.0.0"},
	}
	cands := renderCandidates(recs)
	if len(cands) != 3 {
		t.Fatalf("got %d", len(cands))
	}
	if cands[0].Version != "2.0.0" || cands[2].Version != "1.1.2" {
		t.Errorf("sort order = %v", cands)
	}
}

func TestPromptAccept(t *testing.T) {
	if !promptAccept("") || !promptAccept("y") || !promptAccept("Y") {
		t.Error("y/empty should accept")
	}
	if promptAccept("n") || promptAccept("N") {
		t.Error("n/N should reject")
	}
}

func TestParseEditTextSpecs(t *testing.T) {
	input := "# 注释行\nmdrive: 1.2.3\nmdrive_conf: 2.0.0\nmdrive_map: 3.3.3\n"
	targets := vmc.ParseEditText(input, vmc.DefaultVersionSpecs())
	if len(targets) != 3 {
		t.Fatalf("got %d targets: %+v", len(targets), targets)
	}
	// mdrive must not have swallowed mdrive_conf.
	if targets[0].Name != "mdrive" || targets[0].Version != "1.2.3" {
		t.Errorf("targets[0] = %+v", targets[0])
	}
}

func TestPrepPkgDir(t *testing.T) {
	home := t.TempDir()
	pkgDir := filepath.Join(home, ".vmc", "softwares", "mdrive")
	if err := os.MkdirAll(pkgDir, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("VMC_HOME", filepath.Join(home, ".vmc"))

	var got []string
	r := func(ctx context.Context, name string, args ...string) (string, string, int, error) {
		got = append(got, strings.Join(append([]string{name}, args...), " "))
		return "", "", 0, nil
	}
	v := vmcNew(r)
	v.Cfg.DefaultUser = "nvidia"
	v.prepPkgDir(context.Background(), "mdrive")

	want := "sudo chown -R nvidia:nvidia " + pkgDir
	if len(got) != 1 || got[0] != want {
		t.Errorf("got chown = %v, want %q", got, want)
	}
}

func TestPrepPkgDirNoopWhenAbsent(t *testing.T) {
	t.Setenv("VMC_HOME", filepath.Join(t.TempDir(), ".vmc-unused"))
	var got []string
	r := func(ctx context.Context, name string, args ...string) (string, string, int, error) {
		got = append(got, name)
		return "", "", 0, nil
	}
	v := vmcNew(r)
	v.prepPkgDir(context.Background(), "does_not_exist")
	if len(got) != 0 {
		t.Errorf("absent pkg should not chown, got %v", got)
	}
}

func TestPrepPkgDirEmptyPkgNoop(t *testing.T) {
	var called bool
	r := func(ctx context.Context, name string, args ...string) (string, string, int, error) {
		called = true
		return "", "", 0, nil
	}
	vmcNew(r).prepPkgDir(context.Background(), "")
	if called {
		t.Error("empty pkg must not run any command")
	}
}
