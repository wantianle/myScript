package transfer

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func newLocalTransport(t *testing.T) (*LocalDirTransport, string) {
	t.Helper()
	root := t.TempDir()
	return NewLocalDirTransport(root), root
}

func assertLocalFile(t *testing.T, path string, want []byte) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("%s: got %d bytes, want %d", path, len(got), len(want))
	}
}

// tmpResidueIn returns .md_tmp-* staging file names left in dir (they must
// never survive a copy).
func tmpResidueIn(t *testing.T, dir string) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read dir %s: %v", dir, err)
	}
	var out []string
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".md_tmp-") {
			out = append(out, e.Name())
		}
	}
	return out
}

func TestLocalMkdirAll(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()

	if err := tr.MkdirAll(ctx, "a/b/c"); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	if fi, err := os.Stat(filepath.Join(root, "a/b/c")); err != nil || !fi.IsDir() {
		t.Fatalf("root/a/b/c not created: %v", err)
	}
	// Idempotent: an existing path is not an error.
	if err := tr.MkdirAll(ctx, "a/b/c"); err != nil {
		t.Fatalf("MkdirAll idempotent: %v", err)
	}
	if _, err := tr.Stat(ctx, "a/b/c"); err != nil {
		t.Fatalf("Stat: %v", err)
	}
}

func TestLocalCopyFile(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "f.bin", testContent(300_000))

	if err := tr.CopyFile(ctx, src, "sub/dst.bin", CopyOptions{}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	assertLocalFile(t, filepath.Join(root, "sub/dst.bin"), testContent(300_000))

	if err := tr.CopyFile(ctx, src, "sub/dst.bin", CopyOptions{}); !errors.Is(err, ErrFileExists) {
		t.Fatalf("second CopyFile = %v, want ErrFileExists", err)
	}
	if err := tr.CopyFile(ctx, src, "sub/dst.bin", CopyOptions{Overwrite: true}); err != nil {
		t.Fatalf("CopyFile overwrite: %v", err)
	}
	assertLocalFile(t, filepath.Join(root, "sub/dst.bin"), testContent(300_000))
}

func TestLocalCopyFileSkipSame(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "src.txt", testContent(64*1024))
	fixed := time.Date(2020, 1, 2, 3, 4, 5, 0, time.UTC)
	if err := os.Chtimes(src, fixed, fixed); err != nil {
		t.Fatal(err)
	}

	var copied int64
	opts := CopyOptions{SkipSame: true, PreserveMeta: true, Progress: func(w, _ int64) { copied = w }}
	if err := tr.CopyFile(ctx, src, "skip/same.txt", opts); err != nil {
		t.Fatalf("first copy: %v", err)
	}
	if copied != 64*1024 {
		t.Fatalf("first copy bytes = %d, want %d", copied, 64*1024)
	}

	copied = 0
	if err := tr.CopyFile(ctx, src, "skip/same.txt", opts); err != nil {
		t.Fatalf("second copy: %v", err)
	}
	if copied != 0 {
		t.Fatalf("second copy bytes = %d, want 0 (skipped)", copied)
	}
	fi, err := os.Stat(filepath.Join(root, "skip/same.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if !fi.ModTime().Truncate(time.Second).Equal(fixed) {
		t.Errorf("dst mtime = %v, want %v", fi.ModTime(), fixed)
	}
}

func TestLocalCopyFileAtomicWrite(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "big.bin", testContent(1<<20))

	if err := tr.CopyFile(ctx, src, "atomic/out.bin", CopyOptions{}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	assertLocalFile(t, filepath.Join(root, "atomic/out.bin"), testContent(1<<20))
	if residue := tmpResidueIn(t, filepath.Join(root, "atomic")); len(residue) != 0 {
		t.Fatalf("staging files left after success: %v", residue)
	}
}

// TestLocalCopyFileAtomicAbort mirrors the SFTP abort test: cancelling from
// the first Progress callback happens after the first 128 KiB chunk is staged,
// and the next read observes ctx cancellation.
func TestLocalCopyFileAtomicAbort(t *testing.T) {
	tr, root := newLocalTransport(t)
	src := writeFile(t, t.TempDir(), "big.bin", testContent(1<<20))

	ctx, cancel := context.WithCancel(context.Background())
	err := tr.CopyFile(ctx, src, "atomic/aborted.bin", CopyOptions{Progress: func(_, _ int64) { cancel() }})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled CopyFile = %v, want context.Canceled", err)
	}
	if _, serr := os.Stat(filepath.Join(root, "atomic/aborted.bin")); !errors.Is(serr, os.ErrNotExist) {
		t.Fatalf("dst exists after abort: %v", serr)
	}
	if residue := tmpResidueIn(t, filepath.Join(root, "atomic")); len(residue) != 0 {
		t.Fatalf("staging files left after abort: %v", residue)
	}
}

func TestLocalCopyFilePreserveMeta(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "meta.txt", []byte("meta"))
	if err := os.Chmod(src, 0o640); err != nil {
		t.Fatal(err)
	}
	fixed := time.Date(2021, 6, 7, 8, 9, 10, 0, time.UTC)
	if err := os.Chtimes(src, fixed, fixed); err != nil {
		t.Fatal(err)
	}

	if err := tr.CopyFile(ctx, src, "meta/dst.txt", CopyOptions{PreserveMeta: true}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	fi, err := os.Stat(filepath.Join(root, "meta/dst.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if fi.Mode().Perm() != 0o640 {
		t.Errorf("dst perm = %o, want 640", fi.Mode().Perm())
	}
	if !fi.ModTime().Truncate(time.Second).Equal(fixed) {
		t.Errorf("dst mtime = %v, want %v", fi.ModTime(), fixed)
	}
}

func TestLocalCopyDir(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := buildSourceTree(t)

	if err := tr.CopyDir(ctx, src, "tree", CopyOptions{}); err != nil {
		t.Fatalf("CopyDir: %v", err)
	}
	assertLocalFile(t, filepath.Join(root, "tree/root.txt"), []byte("root-data"))
	assertLocalFile(t, filepath.Join(root, "tree/a/f1.txt"), []byte("a-f1"))
	assertLocalFile(t, filepath.Join(root, "tree/a/b/f2.txt"), []byte("a-b-f2"))
	assertLocalFile(t, filepath.Join(root, "tree/single/only.txt"), []byte("single-only"))
	if fi, err := os.Stat(filepath.Join(root, "tree/empty")); err != nil || !fi.IsDir() {
		t.Fatalf("tree/empty not preserved as empty dir: %v", err)
	}
}

func TestLocalCopyDirFollowLinks(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := buildLinkTree(t)

	// FollowLinks=false: links are shipped verbatim, nothing is dereferenced.
	if err := tr.CopyDir(ctx, src, "plain", CopyOptions{}); err != nil {
		t.Fatal(err)
	}
	if fi, err := os.Lstat(filepath.Join(root, "plain/linkfile")); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("plain/linkfile should be a symlink: fi=%v err=%v", fi, err)
	}
	if fi, err := os.Lstat(filepath.Join(root, "plain/linkdir")); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("plain/linkdir should be a symlink: fi=%v err=%v", fi, err)
	}
	assertLocalFile(t, filepath.Join(root, "plain/cycle/c.txt"), []byte("cycle-content"))

	// FollowLinks=true: file link dereferenced, dir link recursed, cycle guarded.
	if err := tr.CopyDir(ctx, src, "follow", CopyOptions{FollowLinks: true}); err != nil {
		t.Fatal(err)
	}
	fi, err := os.Lstat(filepath.Join(root, "follow/linkfile"))
	if err != nil {
		t.Fatal(err)
	}
	if fi.Mode()&os.ModeSymlink != 0 || !fi.Mode().IsRegular() {
		t.Fatal("follow/linkfile should be a regular file")
	}
	assertLocalFile(t, filepath.Join(root, "follow/linkfile"), []byte("target-content"))
	if fi, err := os.Lstat(filepath.Join(root, "follow/linkdir")); err != nil || fi.Mode()&os.ModeSymlink != 0 || !fi.IsDir() {
		t.Fatalf("follow/linkdir should be a real directory: fi=%v err=%v", fi, err)
	}
	assertLocalFile(t, filepath.Join(root, "follow/linkdir/inner.txt"), []byte("inner-content"))
	assertLocalFile(t, filepath.Join(root, "follow/cycle/c.txt"), []byte("cycle-content"))
	if _, err := os.Lstat(filepath.Join(root, "follow/cycle/sub/up")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("follow/cycle/sub/up should be skipped by the cycle guard, got %v", err)
	}
}

func TestLocalRejectsRootEscape(t *testing.T) {
	tr, root := newLocalTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "f.txt", []byte("data"))

	for _, dst := range []string{"../evil", "sub/../../evil", "/../../evil", "a/../.."} {
		if err := tr.MkdirAll(ctx, dst); err == nil {
			t.Errorf("MkdirAll(%q) = nil, want escape rejection", dst)
		}
		if err := tr.CopyFile(ctx, src, dst+"/f.txt", CopyOptions{}); err == nil {
			t.Errorf("CopyFile(%q) = nil, want escape rejection", dst)
		}
		if err := tr.CopyDir(ctx, src, dst, CopyOptions{}); err == nil {
			t.Errorf("CopyDir(%q) = nil, want escape rejection", dst)
		}
	}

	// Nothing was created at the escaped location or under root.
	if _, err := os.Lstat(filepath.Join(filepath.Dir(root), "evil")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("file escaped root: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(root, "evil")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("file created under root despite rejection: %v", err)
	}
}

func TestLocalRejectsEmptyRoot(t *testing.T) {
	tr := NewLocalDirTransport("")
	if err := tr.MkdirAll(context.Background(), "x"); err == nil {
		t.Fatal("MkdirAll with empty root = nil, want error")
	}
	if err := tr.CopyFile(context.Background(), "/etc/hostname", "x", CopyOptions{}); err == nil {
		t.Fatal("CopyFile with empty root = nil, want error")
	}
}
