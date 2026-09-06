package export

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"mdrive/md/internal/transfer"
)

// Item is one candidate file/dir under MDRIVE_DATA_ROOT selected for export.
// Rel is the path relative to MDRIVE_DATA_ROOT (as the Bash find produces, so
// the push rebuilds the same tree on the target via the Transport's relative
// handling).
type Item struct {
	Rel string
}

// PushOptions configures one export run.
type PushOptions struct {
	DataRoot    string // MDRIVE_DATA_ROOT to scan (default "/mdrive_data" via MDRIVE_DATA_ROOT env)
	Dest        string // the already-resolved target destination (e.g. /media/mdrive_export/<ts>)
	Tgt         Target
	User        string
	Transport   transfer.Transport      // LocalDirTransport (tests/offline) or SFTPTransport (real)
	SelectFiles func([]string) []string // optional file picker (TUI); nil = all files
	Log         func(level, msg string) // optional logger; nil = no-op
}

// ScanDataRoot lists non-hidden paths under dataRoot up to depth 3, mirroring
// md.sh's `find -L . -mindepth 1 -maxdepth 3 -not -path '*/.*'` (md.sh sys::export
// :595). It returns the relative path of each entry (sorted, like `sort`).
func ScanDataRoot(dataRoot string) ([]string, error) {
	var out []string
	err := filepath.WalkDir(dataRoot, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // skip unreadable entries (Bash find -L swallows errors)
		}
		if p == dataRoot {
			return nil
		}
		rel, rerr := filepath.Rel(dataRoot, p)
		if rerr != nil {
			return nil
		}
		// Depth <= 3, mirroring md.sh maxdepth 3; walk counts from dataRoot.
		depth := strings.Count(rel, string(filepath.Separator)) + 1
		if depth > 3 {
			// Skip the subtree entirely for dirs (don't recurse deeper than 3).
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if isHiddenRel(rel) {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		out = append(out, filepath.ToSlash(rel))
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Strings(out)
	return out, nil
}

func isHiddenRel(rel string) bool {
	for _, part := range strings.Split(rel, "/") {
		if strings.HasPrefix(part, ".") {
			return true
		}
	}
	return false
}

// Export runs the push for the selected items. When opts.SelectFiles is nil,
// it selects every scanned item. It creates the destination dir, then copies
// each item, returning the first push error (md.sh :609-631).
func Export(ctx context.Context, opts PushOptions) (int, error) {
	items, err := ScanDataRoot(opts.DataRoot)
	if err != nil {
		return 0, err
	}
	if len(items) == 0 {
		return 0, fmt.Errorf("未扫描到任何可导出内容: %s", opts.DataRoot)
	}
	selected := items
	if opts.SelectFiles != nil {
		selected = opts.SelectFiles(items)
	}
	if len(selected) == 0 {
		opts.logf("warn", "已取消操作")
		return 0, nil
	}

	if err := opts.Transport.MkdirAll(ctx, opts.Dest); err != nil {
		return 0, fmt.Errorf("目标目录创建失败: %s: %w", opts.Dest, err)
	}

	failed := 0
	for _, rel := range selected {
		opts.logf("info", "传输 %s ...", rel)
		src := filepath.Join(opts.DataRoot, filepath.FromSlash(rel))
		dst := opts.Dest + "/" + rel
		// A directory is pushed recursively (rsync -aP -R on a dir copies the
		// whole subtree); a regular file is copied in place.
		info, serr := os.Stat(src)
		if serr != nil {
			opts.logf("err", "无法访问: %s (%v)", rel, serr)
			failed++
			continue
		}
		co := transfer.CopyOptions{FollowLinks: true, Overwrite: true}
		var err error
		if info.IsDir() {
			err = opts.Transport.CopyDir(ctx, src, dst, co)
		} else {
			err = opts.Transport.CopyFile(ctx, src, dst, co)
		}
		if err != nil {
			opts.logf("err", "传输中断: %s (%v)", rel, err)
			failed++
		}
	}
	if failed > 0 {
		return failed, fmt.Errorf("部分文件导出失败，请检查本地电脑网络/磁盘空间/路径权限后重试")
	}
	return 0, nil
}

func (o PushOptions) logf(level, format string, args ...any) {
	if o.Log != nil {
		o.Log(level, fmt.Sprintf(format, args...))
	}
}
