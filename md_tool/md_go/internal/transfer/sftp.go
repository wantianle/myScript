package transfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

// ErrFileExists is returned by CopyFile / CopyDir (via copyFileContent) when
// the destination already exists and CopyOptions.Overwrite is false. Callers
// that treat "already there" as success should either set Overwrite or use
// SkipSame so unchanged files are reported as up-to-date (nil) instead.
var ErrFileExists = errors.New("destination already exists")

// CopyOptions controls one copy operation. The zero value is valid: it means
// no overwrite, no skip, no metadata preservation, no symlink following and
// atomic staging.
type CopyOptions struct {
	Overwrite bool // 覆盖已存在的同名目标文件
	// SkipSame 远端 size+mtime 相同则跳过（rsync 语义）。仅比较秒级 mtime，
	// 因为 SFTP 时间戳精度为秒。
	SkipSame     bool
	PreserveMeta bool // 上传后远端 Chmod+Chtimes 同步源元数据（rsync -a 的权限+时间部分）
	FollowLinks  bool // -L：symlink 解析为目标内容复制（目录手动递归+防环）
	// AtomicWrite 默认 true：写 .md_tmp-<pid> 再 Rename（防半截脏文件）。
	// 注意：Go bool 无法区分“显式 false”与“零值”，本版本始终启用原子写入
	//（零值即默认 true），该字段保留用于后续版本关闭。
	AtomicWrite bool
	Progress    func(written int64, total int64)
}

// Transport is the copy surface used by the G5 export orchestration. Every
// method operates on the DESTINATION side (remote host for SFTPTransport, a
// local root directory for LocalDirTransport); the source is always a local
// path on the machine running md.
type Transport interface {
	MkdirAll(ctx context.Context, path string) error            // 远端
	Stat(ctx context.Context, path string) (os.FileInfo, error) // 远端
	CopyFile(ctx context.Context, srcLocal, dstRemote string, opts CopyOptions) error
	CopyDir(ctx context.Context, srcLocal, dstRemote string, opts CopyOptions) error
}

// SFTPTransport uploads local files and directories to a remote host over an
// established SSH connection.
type SFTPTransport struct {
	Client *sftp.Client
}

// NewSFTPTransport opens the SFTP subsystem on conn (mirroring md.sh running
// rsync with `-e ssh`, except the transport now reuses the pooled SSH
// connection obtained from sshx.Client.SSHClient).
func NewSFTPTransport(conn *ssh.Client) (*SFTPTransport, error) {
	client, err := sftp.NewClient(conn)
	if err != nil {
		return nil, fmt.Errorf("sftp: open subsystem: %w", err)
	}
	return &SFTPTransport{Client: client}, nil
}

// Close shuts down the SFTP subsystem channel. The underlying SSH connection
// is owned by the caller and stays open.
func (t *SFTPTransport) Close() error {
	return t.Client.Close()
}

// MkdirAll creates path and any missing parents on the remote host. It is
// idempotent (like os.MkdirAll / the rsync implicit dir creation).
func (t *SFTPTransport) MkdirAll(ctx context.Context, path string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return t.Client.MkdirAll(path)
}

// Stat returns remote file info for path (following symlinks).
func (t *SFTPTransport) Stat(ctx context.Context, path string) (os.FileInfo, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return t.Client.Stat(path)
}

// CopyFile uploads the local file srcLocal to dstRemote, creating missing
// remote parent directories (rsync does the same implicitly). See the package
// doc for the existence / skip / metadata semantics.
func (t *SFTPTransport) CopyFile(ctx context.Context, srcLocal, dstRemote string, opts CopyOptions) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return copyFileContent(ctx, sftpRemote{t.Client}, srcLocal, dstRemote, opts)
}

// CopyDir uploads the local directory srcLocal (and its whole subtree) into
// dstRemote. Files that exist on the remote but not in the source are left in
// place — there is no --delete equivalent, matching md.sh's rsync usage.
func (t *SFTPTransport) CopyDir(ctx context.Context, srcLocal, dstRemote string, opts CopyOptions) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return copyDirTo(ctx, sftpRemote{t.Client}, srcLocal, dstRemote, opts)
}

// Remove deletes a remote file or directory (specific methods that are NOT on
// the Transport interface, so callers can use them when they know the
// concrete transport).
func (t *SFTPTransport) Remove(ctx context.Context, path string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return t.Client.Remove(path)
}

// Rename moves a remote path atomically.
func (t *SFTPTransport) Rename(ctx context.Context, oldPath, newPath string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return t.Client.Rename(oldPath, newPath)
}

// copyWithProgress copies src into dst in 128 KiB chunks, invoking progress
// after each chunk with the cumulative written byte count. It is the sole
// data pump for every copy in this package; kept as-is from the G1 stub.
func copyWithProgress(dst io.Writer, src io.Reader, total int64, progress func(int64, int64)) error {
	buffer := make([]byte, 128*1024)
	var written int64
	for {
		n, readErr := src.Read(buffer)
		if n > 0 {
			if _, err := dst.Write(buffer[:n]); err != nil {
				return err
			}
			written += int64(n)
			if progress != nil {
				progress(written, total)
			}
		}
		if readErr == io.EOF {
			return nil
		}
		if readErr != nil {
			return readErr
		}
	}
}

// sftpRemote adapts *sftp.Client to the internal copy-core interface.
type sftpRemote struct{ cli *sftp.Client }

func (r sftpRemote) mkdirAll(p string) error { return r.cli.MkdirAll(p) }
func (r sftpRemote) stat(p string) (os.FileInfo, error) {
	return r.cli.Stat(p)
}
func (r sftpRemote) lstat(p string) (os.FileInfo, error) {
	return r.cli.Lstat(p)
}
func (r sftpRemote) readlink(p string) (string, error) { return r.cli.ReadLink(p) }
func (r sftpRemote) create(p string) (io.WriteCloser, error) {
	return r.cli.Create(p)
}
func (r sftpRemote) rename(oldPath, newPath string) error { return r.cli.Rename(oldPath, newPath) }
func (r sftpRemote) remove(p string) error                { return r.cli.Remove(p) }
func (r sftpRemote) chmod(p string, mode os.FileMode) error {
	return r.cli.Chmod(p, mode)
}
func (r sftpRemote) chtimes(p string, atime, mtime time.Time) error {
	return r.cli.Chtimes(p, atime, mtime)
}
func (r sftpRemote) symlink(target, p string) error { return r.cli.Symlink(target, p) }

// remote is the destination-side filesystem abstraction shared by
// copyFileContent / copyDirTo. sftpRemote uploads over SFTP; localRemote (in
// localdir.go) operates on a local tree.
type remote interface {
	mkdirAll(path string) error
	stat(path string) (os.FileInfo, error)
	lstat(path string) (os.FileInfo, error)
	readlink(path string) (string, error)
	create(path string) (io.WriteCloser, error)
	rename(oldPath, newPath string) error
	remove(path string) error
	chmod(path string, mode os.FileMode) error
	chtimes(path string, atime, mtime time.Time) error
	symlink(target, path string) error
}

// ctxReader makes a copy loop cancellable: it surfaces ctx.Err() before every
// read, so copyWithProgress aborts between its 128 KiB chunks.
type ctxReader struct {
	ctx context.Context
	r   io.Reader
}

func (cr ctxReader) Read(p []byte) (int, error) {
	if err := cr.ctx.Err(); err != nil {
		return 0, err
	}
	return cr.r.Read(p)
}

// copyFileContent copies the local file src into dst with the option
// semantics described on CopyOptions. dst is a path understood by r (a remote
// path for sftpRemote, an already-resolved local path for localRemote).
func copyFileContent(ctx context.Context, r remote, src, dst string, opts CopyOptions) error {
	info, err := os.Stat(src) // follows symlinks; CopyFile callers pass the link and FollowLinks decides
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("copy file: %s is not a regular file", src)
	}
	if err := ctx.Err(); err != nil {
		return err
	}

	// Destination policy: SkipSame beats Overwrite beats ErrFileExists.
	if rfi, lerr := r.lstat(dst); lerr == nil {
		if rfi.IsDir() {
			return fmt.Errorf("%w: %s is a directory", ErrFileExists, dst)
		}
		if rfi.Mode()&os.ModeSymlink != 0 {
			if opts.SkipSame {
				if ti, serr := r.stat(dst); serr == nil && sameRegular(ti, info) {
					return nil
				}
			}
			if !opts.Overwrite {
				return fmt.Errorf("%w: %s", ErrFileExists, dst)
			}
			if err := r.remove(dst); err != nil {
				return err
			}
		} else {
			if opts.SkipSame && sameRegular(rfi, info) {
				return nil
			}
			if !opts.Overwrite {
				return fmt.Errorf("%w: %s", ErrFileExists, dst)
			}
		}
	} else if !errors.Is(lerr, fs.ErrNotExist) {
		return lerr
	}

	if err := r.mkdirAll(path.Dir(dst)); err != nil {
		return err
	}

	dw, err := beginWrite(r, dst)
	if err != nil {
		return err
	}
	srcFile, err := os.Open(src)
	if err != nil {
		dw.abort()
		return err
	}
	defer srcFile.Close()

	if err := copyWithProgress(dw.w, ctxReader{ctx: ctx, r: srcFile}, info.Size(), opts.Progress); err != nil {
		dw.abort()
		return err
	}
	if err := dw.commit(); err != nil {
		return err
	}

	if opts.PreserveMeta {
		if err := r.chmod(dst, info.Mode().Perm()); err != nil {
			return err
		}
		at, mt := fileTimes(info)
		if err := r.chtimes(dst, at, mt); err != nil {
			return err
		}
	}
	return nil
}

// sameRegular reports whether the destination is a regular file with the same
// size and second-granularity mtime as the source — rsync's up-to-date check.
func sameRegular(dst os.FileInfo, src os.FileInfo) bool {
	return dst.Mode().IsRegular() &&
		dst.Size() == src.Size() &&
		dst.ModTime().Truncate(time.Second).Equal(src.ModTime().Truncate(time.Second))
}

// destWriter stages a copy: data is written to a .md_tmp-<pid> sibling file
// (so dst never appears half-written) and commit() renames it into place.
type destWriter struct {
	r     remote
	final string
	tmp   string
	w     io.WriteCloser
	mu    sync.Mutex
}

// beginWrite opens the staging file next to dst. Only one staging name is
// used per dst (pid-suffixed), matching the ".md_tmp-<pid>" contract.
func beginWrite(r remote, dst string) (*destWriter, error) {
	tmp := dst + fmt.Sprintf(".md_tmp-%d", os.Getpid())
	w, err := r.create(tmp)
	if err != nil {
		return nil, err
	}
	return &destWriter{r: r, final: dst, tmp: tmp, w: w}, nil
}

// commit flushes and renames the staging file onto dst.
func (dw *destWriter) commit() error {
	dw.mu.Lock()
	defer dw.mu.Unlock()
	if err := dw.w.Close(); err != nil {
		_ = dw.r.remove(dw.tmp)
		return err
	}
	if err := dw.r.rename(dw.tmp, dw.final); err != nil {
		_ = dw.r.remove(dw.tmp)
		return err
	}
	return nil
}

// abort discards the staging file after a failed copy.
func (dw *destWriter) abort() {
	dw.mu.Lock()
	defer dw.mu.Unlock()
	_ = dw.w.Close()
	_ = dw.r.remove(dw.tmp)
}

// copySymlink replicates a symlink verbatim on the destination (rsync's
// default, non -L behaviour): the link is recreated with the same target
// string, nothing is dereferenced.
func copySymlink(r remote, src, dst string, opts CopyOptions) error {
	target, err := os.Readlink(src)
	if err != nil {
		return err
	}
	if rfi, lerr := r.lstat(dst); lerr == nil {
		if rfi.IsDir() {
			return fmt.Errorf("%w: %s is a directory", ErrFileExists, dst)
		}
		if opts.SkipSame && rfi.Mode()&os.ModeSymlink != 0 {
			if rt, rerr := r.readlink(dst); rerr == nil && rt == target {
				return nil
			}
		}
		if !opts.Overwrite {
			return fmt.Errorf("%w: %s", ErrFileExists, dst)
		}
		if err := r.remove(dst); err != nil {
			return err
		}
	} else if !errors.Is(lerr, fs.ErrNotExist) {
		return lerr
	}
	if err := r.mkdirAll(path.Dir(dst)); err != nil {
		return err
	}
	return r.symlink(target, dst)
}

// dirMeta remembers destination-directory metadata to apply after the whole
// tree is copied (a directory's mtime is rewritten every time a child lands
// in it, so it must be set last, deepest first).
type dirMeta struct {
	path  string
	mode  os.FileMode
	atime time.Time
	mtime time.Time
}

// copyDirTo copies the local directory srcLocal into dst (contents of src
// land under dst), creating dst and every nested directory. When FollowLinks
// is set, directory symlinks are resolved and their targets are walked with a
// cycle guard (a symlink chain that returns to an already-copied real
// directory is skipped instead of recursing forever).
func copyDirTo(ctx context.Context, r remote, srcLocal, dst string, opts CopyOptions) error {
	srcInfo, err := os.Lstat(srcLocal)
	if err != nil {
		return err
	}
	if srcInfo.Mode()&os.ModeSymlink != 0 {
		if !opts.FollowLinks {
			return copySymlink(r, srcLocal, dst, opts)
		}
		if srcInfo, err = os.Stat(srcLocal); err != nil {
			return fmt.Errorf("follow %s: %w", srcLocal, err)
		}
	}
	if !srcInfo.IsDir() {
		return fmt.Errorf("copy dir: %s is not a directory", srcLocal)
	}
	real, err := filepath.EvalSymlinks(srcLocal)
	if err != nil {
		return err
	}
	guard := map[string]bool{real: true}

	if err := r.mkdirAll(dst); err != nil {
		return err
	}
	var metas []dirMeta
	if opts.PreserveMeta {
		metas = append(metas, metaFor(srcInfo, dst))
	}
	if err := walkDirContents(ctx, r, real, dst, opts, guard, &metas); err != nil {
		return err
	}
	if opts.PreserveMeta {
		for i := len(metas) - 1; i >= 0; i-- { // deepest first
			m := metas[i]
			if err := r.chmod(m.path, m.mode); err != nil {
				return err
			}
			if err := r.chtimes(m.path, m.atime, m.mtime); err != nil {
				return err
			}
		}
	}
	return nil
}

func walkDirContents(ctx context.Context, r remote, srcDir, dstDir string, opts CopyOptions, guard map[string]bool, metas *[]dirMeta) error {
	return filepath.WalkDir(srcDir, func(p string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		if p == srcDir {
			return nil
		}
		rel, err := filepath.Rel(srcDir, p)
		if err != nil {
			return err
		}
		dst := filepath.Join(dstDir, rel)

		switch {
		case d.IsDir():
			if err := r.mkdirAll(dst); err != nil {
				return err
			}
			if opts.PreserveMeta {
				if info, ierr := os.Stat(p); ierr == nil {
					*metas = append(*metas, metaFor(info, dst))
				}
			}
			return nil

		case d.Type()&fs.ModeSymlink != 0 && !opts.FollowLinks:
			// rsync default: ship the link itself, never descend.
			return copySymlink(r, p, dst, opts)

		case d.Type()&fs.ModeSymlink != 0: // FollowLinks: dereference
			target, err := os.Stat(p)
			if err != nil {
				return fmt.Errorf("follow %s: %w", p, err)
			}
			if !target.IsDir() {
				return copyFileContent(ctx, r, p, dst, opts) // os.Stat/Open inside dereference the link
			}
			realTarget, err := filepath.EvalSymlinks(p)
			if err != nil {
				return fmt.Errorf("resolve %s: %w", p, err)
			}
			if guard[realTarget] {
				return nil //防环: target already copied as part of this tree
			}
			guard[realTarget] = true
			if err := r.mkdirAll(dst); err != nil {
				return err
			}
			if opts.PreserveMeta {
				*metas = append(*metas, metaFor(target, dst))
			}
			return walkDirContents(ctx, r, realTarget, dst, opts, guard, metas)

		default: // regular file (and any other non-symlink type falls through to content copy)
			return copyFileContent(ctx, r, p, dst, opts)
		}
	})
}

func metaFor(fi os.FileInfo, dst string) dirMeta {
	at, mt := fileTimes(fi)
	return dirMeta{path: dst, mode: fi.Mode().Perm(), atime: at, mtime: mt}
}

// fileTimes returns the atime and mtime of fi. atime comes from the raw
// syscall.Stat_t (only meaningful on Linux targets, which is the whole
// deployment surface of md); mtime is FileInfo.ModTime.
func fileTimes(fi os.FileInfo) (atime, mtime time.Time) {
	mtime = fi.ModTime()
	atime = mtime
	if st, ok := fi.Sys().(*syscall.Stat_t); ok {
		atime = time.Unix(st.Atim.Sec, st.Atim.Nsec)
	}
	return atime, mtime
}
