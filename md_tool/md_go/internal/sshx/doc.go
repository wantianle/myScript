// Package sshx is the G2 migration of the SSH transport that md_tool/md.sh
// currently performs with the system `ssh` binary. It is a hybrid layer:
//
//   - non-interactive remote commands (Exec / Stream / Ping) run over a pure
//     Go client built on golang.org/x/crypto/ssh — md.sh's `ssh -n ${SSH_OPTS[@]}
//     user@host cmd` equivalent — so md flows no longer depend on a local
//     openssh-client binary once migrated;
//   - interactive flows (Interactive) still exec the system `ssh -t` binary,
//     because they need a real pty, terminal control and password prompts that
//     a pure library cannot provide.
//
// The config defaults mirror the md.sh SSH_OPTS (md.sh:24-32):
//
//	SSH_OPTS=(
//	    -o ConnectTimeout=2
//	    -o ServerAliveInterval=2
//	    -o ServerAliveCountMax=2
//	    -o StrictHostKeyChecking=no
//	    -o UserKnownHostsFile=/dev/null
//	    -o LogLevel=ERROR
//	    -i "$KEY_PATH"
//	)
//
// # md.sh ↔ sshx mapping
//
// | md.sh call                               | sshx call                          |
// |------------------------------------------|------------------------------------|
// | ssh -n ${SSH_OPTS[@]} user@host "cmd"    | Dial + Client.Exec                 |
// | journalctl -f via `ssh -t ...` (svc::log)| Client.Stream (TUI viewport path)  |
// | `ssh ... exit` reachability probes       | Client.Ping                        |
// | `ssh -t ... "export ... && cmd"`         | Client.Interactive                 |
// | StrictHostKeyChecking=no /known_hosts=/dev/null | default HostKeyCallback    |
// | -i $HOME/.ssh/id_ed25519                 | default KeyPath                    |
// | ServerAliveInterval=2 / CountMax=2       | KeepAliveInterval / KeepAliveCountMax |
//
// # Error model
//
// Two sentinels are exported (see errors.go): ErrAuthFailed for anything that
// happens before a session exists (missing/bad/over-permissive key file,
// server rejecting the public key) and ErrConnFailed for transport-layer
// problems (dial, handshake, dead link, closed client). A remote command that
// exits non-zero is NOT an error from Exec — the code is reported in
// ExecResult.ExitCode. Stream and Interactive report remote non-zero exits as
// *ExitError so callers that only look at the error channel still notice them.
//
// # Connection lifecycle
//
// Dial opens one long-lived SSH connection guarded by a keepalive goroutine
// (the analogue of ServerAliveInterval). md.sh runs a fresh `ssh` process per
// command, so a mid-command transport failure never poisons the next command;
// this package reproduces that with dead→redial-once semantics: when an
// operation discovers the connection is gone it tears the connection down and
// returns the transport error, and the NEXT operation transparently dials a
// fresh connection. Individual operations are serialized, like Bash's
// sequential `ssh` invocations.
//
// # Divergences from md.sh (deliberate)
//
//   - md.sh key generation / chmod repair lives in sys::nopasswd; this package
//     only classifies key problems as ErrAuthFailed so a later stage can route
//     to an interactive ssh-keygen / ssh-copy-id flow.
//   - The default 30s per-command wall-clock timeout of ExecRequest.Timeout
//     has no md.sh counterpart (md.sh hangs until the user interrupts). It
//     exists to stop a hung remote command from occupying the pooled
//     connection; on timeout the remote process is killed by dropping the
//     connection, matching the effect of Ctrl-C on `ssh host 'cmd'`.
//   - KeepAliveInterval zero means "use the 2s default"; a negative value
//     disables the keepalive goroutine (md.sh always enables keepalives, so
//     this escape hatch exists for tests only).
//   - No agent forwarding, no ProxyCommand and no per-host ~/.ssh/config
//     reading. md.sh's remotes config is a plain host list, and config file
//     parsing is out of scope for this stage.
package sshx
