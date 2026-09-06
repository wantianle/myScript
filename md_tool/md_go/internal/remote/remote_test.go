package remote

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEntryString(t *testing.T) {
	tests := []struct {
		e    Entry
		want string
	}{
		{Entry{Name: "dev", Branch: "main", Platform: "orin"}, "dev main orin"},
		{Entry{Name: "dev", Branch: "-", Platform: ""}, "dev - "}, // trailing space preserved
	}
	for _, tt := range tests {
		if got := tt.e.String(); got != tt.want {
			t.Errorf("Entry%+v String() = %q, want %q", tt.e, got, tt.want)
		}
	}
}

func TestNameValid(t *testing.T) {
	tests := []struct {
		name string
		ok   bool
	}{
		{"dev", true},
		{"a_b.c", true},
		{"", false},
		{"has space", false},
		{"#comment", false},
	}
	for _, tt := range tests {
		if got := NameValid(tt.name); got != tt.ok {
			t.Errorf("NameValid(%q) = %v, want %v", tt.name, got, tt.ok)
		}
	}
}

func TestAddListDel(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".md_remotes")

	// add
	added, err := Add(path, "dev", "main", "orin")
	if err != nil || !added {
		t.Fatalf("Add(dev) = added %v err %v", added, err)
	}
	// duplicate (same line incl trailing-space logic) not added again
	added, err = Add(path, "dev", "main", "orin")
	if err != nil || added {
		t.Fatalf("Add duplicate should not add; add=%v err=%v", added, err)
	}
	// add empty-platform entry
	if _, err = Add(path, "beta", "-", ""); err != nil {
		t.Fatalf("Add(beta) err = %v", err)
	}

	// list
	lines, err := List(path)
	if err != nil {
		t.Fatalf("List err = %v", err)
	}
	if len(lines) != 2 {
		t.Fatalf("List got %d lines, want 2: %v", len(lines), lines)
	}

	// del existing
	if removed, err := Del(path, "dev"); err != nil || !removed {
		t.Fatalf("Del(dev) removed %v err %v", removed, err)
	}
	lines, _ = List(path)
	if len(lines) != 1 || lines[0] != "beta - " {
		t.Fatalf("after del, got %v", lines)
	}

	// del missing
	if _, err := Del(path, "nope"); err == nil {
		t.Fatal("Del(nope) should error")
	}
	// del on missing file
	if _, err := Del(filepath.Join(dir, "nofile"), "x"); err == nil {
		t.Fatal("Del on missing file should error")
	}
}

func TestAddRejectsBadName(t *testing.T) {
	dir := t.TempDir()
	if _, err := Add(filepath.Join(dir, "f"), "", "main", ""); err == nil {
		t.Fatal("Add with empty name should error")
	}
	if _, err := Add(filepath.Join(dir, "f"), "#x", "main", ""); err == nil {
		t.Fatal("Add with # name should error")
	}
}

func TestListMissingFileReturnsNil(t *testing.T) {
	dir := t.TempDir()
	lines, err := List(filepath.Join(dir, "missing"))
	if err != nil || lines != nil {
		t.Fatalf("List(missing) = %v, %v; want nil, nil", lines, err)
	}
}

func TestDelPreservesOtherLinesAndFormatting(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "f")
	os.WriteFile(path, []byte("dev main orin\nbeta - \ngamma stable amd64\n"), 0o644)
	if removed, err := Del(path, "beta"); err != nil || !removed {
		t.Fatalf("Del err=%v removed=%v", err, removed)
	}
	got, _ := os.ReadFile(path)
	want := "dev main orin\ngamma stable amd64\n"
	if string(got) != want {
		t.Fatalf("after del got %q, want %q", string(got), want)
	}
}
