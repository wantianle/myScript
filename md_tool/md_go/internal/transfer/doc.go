// Package transfer is the G2 migration of the file-transfer paths that
// md_tool/md.sh currently performs with rsync over ssh (md.sh:622):
//
//	rsync -avPL -R -e "ssh ${EXPORT_SSH_OPTS[*]}" "$item" user@host:dest/
//
// md.sh's -a (archive) ≈ PreserveMeta (perms + mtimes; ownership is NOT
// carried because SFTP/rsync-as-user cannot chown to arbitrary owners),
// -P (progress) ≈ CopyOptions.Progress, -L (follow symlinks) ≈
// FollowLinks, and rsync's default size+mtime skip ≈ SkipSame. The default
// "overwrite same-name files into a reused destination directory" behaviour
// of the export flow maps to CopyOptions{Overwrite: true, SkipSame: true,
// PreserveMeta: true, FollowLinks: true}.
//
// The rsync -R (relative) structure preservation is the caller's job: pass a
// dst that mirrors the source path layout, exactly as md.sh does by cd-ing
// into $MDRIVE_DATA_ROOT before rsyncing.
//
// # Transports
//
// SFTPTransport copies a local source tree onto a remote host over the SFTP
// subsystem (pkg/sftp) of an established SSH connection. LocalDirTransport
// copies the same local sources into a plain local directory tree; it exists
// so the G5 orchestration can run the entire export flow offline with
// --local-root, exercising the same Transport interface and destination path
// strings it would later send over SFTP.
//
// # Copy semantics
//
// Every copy stages through a sibling `.md_tmp-<pid>` file and renames it
// into place on success, so an interrupted transfer never leaves a
// half-written file under the final name and a partial .md_tmp is cleaned up
// on failure. mtime comparisons are truncated to whole seconds because the
// SFTP protocol carries second-granularity timestamps (the same granularity
// rsync compares).
//
// # Error model
//
// ErrFileExists reports a destination that already exists while
// CopyOptions.Overwrite is false (and SkipSame did not declare it current).
// Transport failures (network, permission, protocol) are returned unwrapped
// from the underlying ssh/sftp or os layer with enough context to diagnose.
package transfer
