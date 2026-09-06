package transfer

import (
	"context"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

// LocalDirTransport implements Transport against a local directory tree. It
// exists so the G5 export orchestration can run end-to-end offline with
// --local-root: every destination path that would normally be a remote SFTP
// path is interpreted as a path under Root, using the SAME strings the
// SFTPTransport would send. No SSH connection or remote host is involved.
type LocalDirTransport struct {
	Root string
}

// NewLocalDirTransport returns a transport rooted at root. root is not
// created here — callers issue MkdirAll before the first copy, exactly like
// md.sh's sys::export_mkdir step.
func NewLocalDirTransport(root string) *LocalDirTransport {
	return &LocalDirTransport{Root: root}
}

var _ Transport = (*LocalDirTransport)(nil)
var _ Transport = (*SFTPTransport)(nil)

// localRootPath maps a caller-supplied destination to a path under root. A
// leading "/" is tolerated so orchestration can pass remote-style absolute
// paths; a ".." component is rejected so no destination can escape root.
func (t *LocalDirTransport) localRootPath(dst string) (string, error) {
	return localRootPath(t.Root, dst)
}

func localRootPath(root, dst string) (string, error) {
	if root == "" {
		return "", fmt.Errorf("local dir transport: empty root")
	}
	// Reject parent traversal outright: path.Clean below would silently
	// neutralize ".." into the root, hiding a caller bug and making the local
	// transport accept destinations the remote one cannot express.
	for _, part := range strings.Split(dst, "/") {
		if part == ".." {
			return "", fmt.Errorf("local dir transport: path %q escapes root %q", dst, root)
		}
	}
	clean := path.Clean("/" + dst) // force absolute; normalizes "." and trailing slashes
	p := filepath.Join(root, filepath.FromSlash(clean))
	if rel, err := filepath.Rel(root, p); err != nil ||
		rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("local dir transport: path %q escapes root %q", dst, root)
	}
	return p, nil
}

// MkdirAll creates path (and parents) under Root.
func (t *LocalDirTransport) MkdirAll(ctx context.Context, path string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	p, err := t.localRootPath(path)
	if err != nil {
		return err
	}
	return os.MkdirAll(p, 0o755)
}

// Stat returns the info of path under Root (following symlinks).
func (t *LocalDirTransport) Stat(ctx context.Context, path string) (os.FileInfo, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	p, err := t.localRootPath(path)
	if err != nil {
		return nil, err
	}
	return os.Stat(p)
}

// CopyFile copies the local file srcLocal to path under Root. dst is first
// mapped through localRootPath, so it must be an absolute/relative path that
// stays inside Root — identical semantics to SFTPTransport.CopyFile but with
// the local filesystem as the "remote".
func (t *LocalDirTransport) CopyFile(ctx context.Context, srcLocal, dst string, opts CopyOptions) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	p, err := t.localRootPath(dst)
	if err != nil {
		return err
	}
	return copyFileContent(ctx, localRemote{}, srcLocal, p, opts)
}

// CopyDir copies the local directory srcLocal into path under Root.
func (t *LocalDirTransport) CopyDir(ctx context.Context, srcLocal, dst string, opts CopyOptions) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	p, err := t.localRootPath(dst)
	if err != nil {
		return err
	}
	return copyDirTo(ctx, localRemote{}, srcLocal, p, opts)
}

// localRemote adapts plain os operations to the internal copy-core interface.
// The paths it receives are already resolved under the transport root, so no
// further mapping happens here.
type localRemote struct{}

func (localRemote) mkdirAll(p string) error { return os.MkdirAll(p, 0o755) }
func (localRemote) stat(p string) (os.FileInfo, error) {
	return os.Stat(p)
}
func (localRemote) lstat(p string) (os.FileInfo, error) {
	return os.Lstat(p)
}
func (localRemote) readlink(p string) (string, error) { return os.Readlink(p) }
func (localRemote) create(p string) (io.WriteCloser, error) {
	return os.Create(p)
}
func (localRemote) rename(oldPath, newPath string) error {
	return os.Rename(oldPath, newPath)
}
func (localRemote) remove(p string) error { return os.Remove(p) }
func (localRemote) chmod(p string, mode os.FileMode) error {
	return os.Chmod(p, mode)
}
func (localRemote) chtimes(p string, atime, mtime time.Time) error {
	return os.Chtimes(p, atime, mtime)
}
func (localRemote) symlink(target, p string) error { return os.Symlink(target, p) }
