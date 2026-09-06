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

	"mdrive/md/internal/sshtest"
)

// newSFTPTransport starts an in-process ssh+sftp server (sshtest) and returns
// a transport bound to it. Remote paths used in the tests are RELATIVE: the
// pkg/sftp server roots relative paths at its working directory, while an
// absolute path would be interpreted against the real host filesystem.
func newSFTPTransport(t *testing.T) (*SFTPTransport, *sshtest.Server) {
	t.Helper()
	srv := sshtest.NewServer(t)
	conn, err := srv.Dial()
	if err != nil {
		t.Fatalf("dial sshtest server: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	tr, err := NewSFTPTransport(conn)
	if err != nil {
		t.Fatalf("NewSFTPTransport: %v", err)
	}
	t.Cleanup(func() { _ = tr.Close() })
	return tr, srv
}

// remotePath resolves a relative remote path against the server's sftp root
// (the sshtest working directory), so tests can verify what SFTP actually
// wrote by reading the server-side filesystem directly.
func remotePath(srv *sshtest.Server, rel string) string {
	return filepath.Join(srv.WorkDir(), filepath.FromSlash(rel))
}

// testContent returns n deterministic bytes. The pattern does not repeat at
// the 128 KiB chunk size, so chunk misalignment is detected by byte compare.
func testContent(n int) []byte {
	b := make([]byte, n)
	for i := range b {
		b[i] = byte(i*31 + 7)
	}
	return b
}

// writeFile creates a local source file with deterministic content, creating
// missing parents.
func writeFile(t *testing.T, dir, name string, content []byte) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, content, 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

// assertRemoteFile checks the server-side file at relative path rel has
// exactly the wanted bytes.
func assertRemoteFile(t *testing.T, srv *sshtest.Server, rel string, want []byte) {
	t.Helper()
	got, err := os.ReadFile(remotePath(srv, rel))
	if err != nil {
		t.Fatalf("read remote %s: %v", rel, err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("remote %s: got %d bytes, want %d", rel, len(got), len(want))
	}
}

// listTmpResidue returns the names of .md_tmp-* staging files left in a
// remote directory (they must never survive a copy).
func listTmpResidue(t *testing.T, srv *sshtest.Server, remoteDir string) []string {
	t.Helper()
	entries, err := os.ReadDir(remotePath(srv, remoteDir))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		t.Fatalf("read remote dir %s: %v", remoteDir, err)
	}
	var out []string
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".md_tmp-") {
			out = append(out, e.Name())
		}
	}
	return out
}

// buildSourceTree creates the canonical G2 source tree:
//
//	src/
//	  root.txt
//	  a/f1.txt
//	  a/b/f2.txt
//	  empty/
//	  single/only.txt
func buildSourceTree(t *testing.T) string {
	t.Helper()
	src := t.TempDir()
	writeFile(t, src, "root.txt", []byte("root-data"))
	writeFile(t, src, "a/f1.txt", []byte("a-f1"))
	writeFile(t, src, "a/b/f2.txt", []byte("a-b-f2"))
	if err := os.MkdirAll(filepath.Join(src, "empty"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, src, "single/only.txt", []byte("single-only"))
	return src
}

// buildLinkTree creates a source tree exercising every FollowLinks branch:
//
//	src/
//	  file.txt
//	  linkfile -> file.txt        (file symlink)
//	  reldir/inner.txt
//	  linkdir -> reldir           (dir symlink)
//	  cycle/c.txt
//	  cycle/sub/up -> ../..       (resolves to the tree root — the cycle)
func buildLinkTree(t *testing.T) string {
	t.Helper()
	src := t.TempDir()
	writeFile(t, src, "file.txt", []byte("target-content"))
	if err := os.Symlink("file.txt", filepath.Join(src, "linkfile")); err != nil {
		t.Fatal(err)
	}
	writeFile(t, src, "reldir/inner.txt", []byte("inner-content"))
	if err := os.Symlink("reldir", filepath.Join(src, "linkdir")); err != nil {
		t.Fatal(err)
	}
	writeFile(t, src, "cycle/c.txt", []byte("cycle-content"))
	if err := os.MkdirAll(filepath.Join(src, "cycle/sub"), 0o755); err != nil {
		t.Fatal(err)
	}
	// up -> ../.. resolves to the copied tree root, which is already in the
	// walk's cycle guard: following it must skip instead of recursing forever.
	if err := os.Symlink("../..", filepath.Join(src, "cycle/sub/up")); err != nil {
		t.Fatal(err)
	}
	return src
}

func TestNewSFTPTransport(t *testing.T) {
	tr, _ := newSFTPTransport(t)
	if tr == nil || tr.Client == nil {
		t.Fatal("NewSFTPTransport returned a transport without a client")
	}
	// A round-trip proves the subsystem is actually up.
	if _, err := tr.Stat(context.Background(), "."); err != nil {
		t.Fatalf("Stat(.): %v", err)
	}
}

func TestSFTPMkdirAll(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()

	if err := tr.MkdirAll(ctx, "a/b/c"); err != nil {
		t.Fatalf("MkdirAll(a/b/c): %v", err)
	}
	if fi, err := os.Stat(remotePath(srv, "a/b/c")); err != nil || !fi.IsDir() {
		t.Fatalf("remote a/b/c is not a directory: %v", err)
	}
	// Idempotent: an existing path is not an error.
	if err := tr.MkdirAll(ctx, "a/b/c"); err != nil {
		t.Fatalf("MkdirAll(a/b/c) second time: %v", err)
	}
	// Stat via the transport agrees with the filesystem.
	fi, err := tr.Stat(ctx, "a/b/c")
	if err != nil || !fi.IsDir() {
		t.Fatalf("Stat(a/b/c): fi=%v err=%v", fi, err)
	}
}

func TestSFTPCopyFile(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "data/file.bin", testContent(300_000))

	if err := tr.CopyFile(ctx, src, "exp/data/file.bin", CopyOptions{}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	assertRemoteFile(t, srv, "exp/data/file.bin", testContent(300_000))

	// A second copy without Overwrite is ErrFileExists.
	err := tr.CopyFile(ctx, src, "exp/data/file.bin", CopyOptions{})
	if !errors.Is(err, ErrFileExists) {
		t.Fatalf("second CopyFile = %v, want ErrFileExists", err)
	}
	// Copying onto an existing directory is also ErrFileExists.
	if err := tr.MkdirAll(ctx, "exp/blocked"); err != nil {
		t.Fatal(err)
	}
	err = tr.CopyFile(ctx, src, "exp/blocked", CopyOptions{})
	if !errors.Is(err, ErrFileExists) {
		t.Fatalf("CopyFile onto a dir = %v, want ErrFileExists", err)
	}
}

func TestSFTPCopyFileOverwrite(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	dir := t.TempDir()
	src1 := writeFile(t, dir, "v1.txt", []byte("version one"))
	src2 := writeFile(t, dir, "v2.txt", []byte("version two replaced"))

	if err := tr.CopyFile(ctx, src1, "out.txt", CopyOptions{}); err != nil {
		t.Fatalf("first CopyFile: %v", err)
	}
	assertRemoteFile(t, srv, "out.txt", []byte("version one"))

	// Overwrite replaces the content even though dst already exists.
	if err := tr.CopyFile(ctx, src2, "out.txt", CopyOptions{Overwrite: true}); err != nil {
		t.Fatalf("CopyFile overwrite: %v", err)
	}
	assertRemoteFile(t, srv, "out.txt", []byte("version two replaced"))
}

func TestSFTPCopyFileSkipSame(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()

	dir := t.TempDir()
	src := writeFile(t, dir, "src.txt", testContent(64*1024))
	fixed := time.Date(2020, 1, 2, 3, 4, 5, 0, time.UTC)
	if err := os.Chtimes(src, fixed, fixed); err != nil {
		t.Fatal(err)
	}

	var copied int64
	progress := func(written, total int64) { copied = written }
	opts := CopyOptions{SkipSame: true, PreserveMeta: true, Progress: progress}

	if err := tr.CopyFile(ctx, src, "skip/same.txt", opts); err != nil {
		t.Fatalf("first CopyFile: %v", err)
	}
	if copied != 64*1024 {
		t.Fatalf("first copy reported %d bytes, want %d", copied, 64*1024)
	}

	// Same size + same mtime (PreserveMeta made the remote mtime match): the
	// second copy must skip the write entirely.
	copied = 0
	if err := tr.CopyFile(ctx, src, "skip/same.txt", opts); err != nil {
		t.Fatalf("second CopyFile: %v", err)
	}
	if copied != 0 {
		t.Fatalf("second copy wrote %d bytes, want 0 (skip)", copied)
	}
	// Content and remote mtime are untouched by the skip.
	assertRemoteFile(t, srv, "skip/same.txt", testContent(64*1024))
	rfi, err := os.Stat(remotePath(srv, "skip/same.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if !rfi.ModTime().Truncate(time.Second).Equal(fixed) {
		t.Fatalf("remote mtime = %v, want %v", rfi.ModTime(), fixed)
	}
}

func TestSFTPCopyFileAtomicWrite(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := writeFile(t, t.TempDir(), "big.bin", testContent(1<<20))

	if err := tr.CopyFile(ctx, src, "atomic/out.bin", CopyOptions{}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	assertRemoteFile(t, srv, "atomic/out.bin", testContent(1<<20))
	if residue := listTmpResidue(t, srv, "atomic"); len(residue) != 0 {
		t.Fatalf("staging files left after success: %v", residue)
	}
}

// TestSFTPCopyFileAtomicAbort: cancelling mid-copy must discard the staging
// file and never expose a partial dst. Cancelling from the first Progress
// callback is deterministic: the first 128 KiB chunk is already in the staging
// file, and the next read observes ctx cancellation before EOF.
func TestSFTPCopyFileAtomicAbort(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	src := writeFile(t, t.TempDir(), "big.bin", testContent(1<<20))

	ctx, cancel := context.WithCancel(context.Background())
	err := tr.CopyFile(ctx, src, "atomic/aborted.bin", CopyOptions{Progress: func(_, _ int64) { cancel() }})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled CopyFile = %v, want context.Canceled", err)
	}
	if _, serr := os.Stat(remotePath(srv, "atomic/aborted.bin")); !errors.Is(serr, os.ErrNotExist) {
		t.Fatalf("dst exists after aborted copy: %v", serr)
	}
	if residue := listTmpResidue(t, srv, "atomic"); len(residue) != 0 {
		t.Fatalf("staging files left after abort: %v", residue)
	}
}

func TestSFTPCopyFilePreserveMeta(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()

	dir := t.TempDir()
	src := writeFile(t, dir, "meta.txt", []byte("meta"))
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
	rfi, err := os.Stat(remotePath(srv, "meta/dst.txt"))
	if err != nil {
		t.Fatal(err)
	}
	if rfi.Mode().Perm() != 0o640 {
		t.Errorf("remote perm = %o, want 640", rfi.Mode().Perm())
	}
	if !rfi.ModTime().Truncate(time.Second).Equal(fixed) {
		t.Errorf("remote mtime = %v, want %v", rfi.ModTime(), fixed)
	}
}

func TestSFTPCopyDir(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := buildSourceTree(t)

	if err := tr.CopyDir(ctx, src, "tree", CopyOptions{}); err != nil {
		t.Fatalf("CopyDir: %v", err)
	}
	assertRemoteFile(t, srv, "tree/root.txt", []byte("root-data"))
	assertRemoteFile(t, srv, "tree/a/f1.txt", []byte("a-f1"))
	assertRemoteFile(t, srv, "tree/a/b/f2.txt", []byte("a-b-f2"))
	assertRemoteFile(t, srv, "tree/single/only.txt", []byte("single-only"))
	if fi, err := os.Stat(remotePath(srv, "tree/empty")); err != nil || !fi.IsDir() {
		t.Fatalf("tree/empty not preserved as empty dir: %v", err)
	}
}

func TestSFTPCopyDirPreserveMeta(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := buildSourceTree(t)

	// Freeze the source dir mtimes (applied to dirs only; file writes into a
	// source dir are not part of the walk).
	dirTimes := map[string]time.Time{}
	for _, rel := range []string{"", "a", "a/b", "empty", "single"} {
		p := src
		if rel != "" {
			p = filepath.Join(src, rel)
		}
		mt := time.Date(2022, 3, 4, 5, 6, 7+len(rel), 0, time.UTC)
		dirTimes[rel] = mt
		if err := os.Chtimes(p, mt, mt); err != nil {
			t.Fatal(err)
		}
	}

	if err := tr.CopyDir(ctx, src, "tree", CopyOptions{PreserveMeta: true}); err != nil {
		t.Fatalf("CopyDir: %v", err)
	}
	for _, rel := range []string{"", "a", "a/b", "empty", "single"} {
		p := remotePath(srv, filepath.Join("tree", filepath.FromSlash(rel)))
		fi, err := os.Stat(p)
		if err != nil {
			t.Fatalf("stat remote tree/%s: %v", rel, err)
		}
		if want := dirTimes[rel]; !fi.ModTime().Truncate(time.Second).Equal(want) {
			t.Errorf("remote tree/%s mtime = %v, want %v", rel, fi.ModTime(), want)
		}
	}
}

func TestSFTPCopyDirSymlinkDefault(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := buildLinkTree(t)

	if err := tr.CopyDir(ctx, src, "tree", CopyOptions{}); err != nil {
		t.Fatalf("CopyDir: %v", err)
	}
	// rsync default (no FollowLinks): the link itself is shipped verbatim and
	// nothing is dereferenced.
	if fi, err := os.Lstat(remotePath(srv, "tree/linkfile")); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("tree/linkfile should be a symlink: fi=%v err=%v", fi, err)
	}
	if fi, err := os.Lstat(remotePath(srv, "tree/linkdir")); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("tree/linkdir should be a symlink: fi=%v err=%v", fi, err)
	}
	assertRemoteFile(t, srv, "tree/cycle/c.txt", []byte("cycle-content"))
}

func TestSFTPCopyDirFollowLinks(t *testing.T) {
	tr, srv := newSFTPTransport(t)
	ctx := context.Background()
	src := buildLinkTree(t)

	if err := tr.CopyDir(ctx, src, "tree", CopyOptions{FollowLinks: true}); err != nil {
		t.Fatalf("CopyDir FollowLinks: %v", err)
	}

	// File symlink -> regular file holding the target's content.
	fi, err := os.Lstat(remotePath(srv, "tree/linkfile"))
	if err != nil {
		t.Fatal(err)
	}
	if fi.Mode()&os.ModeSymlink != 0 || !fi.Mode().IsRegular() {
		t.Fatal("tree/linkfile should be a regular file when following links")
	}
	assertRemoteFile(t, srv, "tree/linkfile", []byte("target-content"))

	// Dir symlink -> recursively copied directory tree.
	fi, err = os.Lstat(remotePath(srv, "tree/linkdir"))
	if err != nil || fi.Mode()&os.ModeSymlink != 0 || !fi.IsDir() {
		t.Fatalf("tree/linkdir should be a real directory: fi=%v err=%v", fi, err)
	}
	assertRemoteFile(t, srv, "tree/linkdir/inner.txt", []byte("inner-content"))

	// The cycle (cycle/sub/up -> tree root) is guarded: the copy completes and
	// the loop link is skipped instead of recursing forever.
	assertRemoteFile(t, srv, "tree/cycle/c.txt", []byte("cycle-content"))
	if _, err := os.Lstat(remotePath(srv, "tree/cycle/sub/up")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("tree/cycle/sub/up should be skipped by the cycle guard, got %v", err)
	}
}

func TestSFTPCopyFileProgress(t *testing.T) {
	tr, _ := newSFTPTransport(t)
	ctx := context.Background()
	const size = 300_000
	src := writeFile(t, t.TempDir(), "p.bin", testContent(size))

	var calls []struct{ written, total int64 }
	progress := func(written, total int64) {
		calls = append(calls, struct{ written, total int64 }{written, total})
	}
	if err := tr.CopyFile(ctx, src, "progress/p.bin", CopyOptions{Progress: progress}); err != nil {
		t.Fatalf("CopyFile: %v", err)
	}
	if len(calls) == 0 {
		t.Fatal("Progress callback never called")
	}
	var last int64
	for i, c := range calls {
		if c.total != size {
			t.Errorf("call %d: total = %d, want %d", i, c.total, size)
		}
		if c.written < last {
			t.Errorf("call %d: written not monotonic (%d after %d)", i, c.written, last)
		}
		last = c.written
	}
	if last != size {
		t.Errorf("final written = %d, want %d", last, size)
	}
}

func TestSFTPCopyDirProgress(t *testing.T) {
	tr, _ := newSFTPTransport(t)
	ctx := context.Background()
	src := buildSourceTree(t)

	var total, calls int64
	opts := CopyOptions{Progress: func(written, totalBytes int64) {
		if written > totalBytes {
			t.Errorf("written %d exceeds total %d", written, totalBytes)
		}
		total += written
		calls++
	}}
	if err := tr.CopyDir(ctx, src, "tree", opts); err != nil {
		t.Fatal(err)
	}
	want := int64(len("root-data") + len("a-f1") + len("a-b-f2") + len("single-only"))
	if calls == 0 {
		t.Fatal("Progress never called")
	}
	if total != want {
		t.Errorf("total progress bytes = %d, want %d", total, want)
	}
}
