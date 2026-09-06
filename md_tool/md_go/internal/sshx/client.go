package sshx

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/user"
	"strconv"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"
)

// ClientConfig configures a Client. Every zero value falls back to the md.sh
// SSH_OPTS defaults (md.sh:24-32), so `ClientConfig{Host: "192.168.10.3"}`
// is a valid config.
type ClientConfig struct {
	User    string
	Host    string
	Port    int
	KeyPath string // 默认 ~/.ssh/id_ed25519

	DialTimeout       time.Duration // 默认 2s（对齐 ConnectTimeout=2）
	HandshakeTimeout  time.Duration // 默认 5s（TCP dial 后 SetDeadline 再 NewClientConn，成功清零）
	KeepAliveInterval time.Duration // 默认 2s（对齐 ServerAliveInterval=2）；<0 = 关闭 keepalive
	KeepAliveCountMax int           // 默认 2（对齐 ServerAliveCountMax=2）

	// HostKeyCallback mirrors `-o StrictHostKeyChecking=no -o
	// UserKnownHostsFile=/dev/null`. Defaults to ssh.InsecureIgnoreHostKey().
	HostKeyCallback ssh.HostKeyCallback
}

// defaultExecTimeout bounds a single ExecRequest when req.Timeout is zero. It
// stops a hung remote command from occupying the pooled connection.
const defaultExecTimeout = 30 * time.Second

// defaultPingTimeout bounds a Ping when the caller's context has no deadline.
const defaultPingTimeout = 5 * time.Second

// ExecRequest is one remote command executed under `sh -c` semantics (md.sh
// relies on pipes/&&/for loops inside the command string, which only work
// because ssh hands the string to the remote shell).
type ExecRequest struct {
	Command string        // 远端 shell 命令串（sh -c 语义，支持管道/&&/for）
	Timeout time.Duration // 单命令墙钟超时；0 = 默认 30s 兜底（防挂死命令占连接）
	Stdin   io.Reader     // nil = /dev/null（对齐 ssh -n）
}

// ExecResult carries the captured output of an Exec. The remote exit code
// lives here, NOT in the error value: a non-zero exit is a normal outcome for
// md.sh commands such as `vmc list` greps and supervisor probes.
type ExecResult struct {
	Stdout   []byte
	Stderr   []byte
	ExitCode int
}

// OutputChunk is one incremental slice of a streamed remote command's stdout
// or stderr (the journalctl -f TUI path). Stream is the stream name:
// "stdout" or "stderr".
type OutputChunk struct {
	Stream string
	Data   []byte
}

// Client is a pooled SSH connection with keepalive supervision and
// dead→redial-once behaviour. Create one with Dial; operations (Exec, Stream,
// Ping, Interactive) are serialized like Bash's sequential ssh invocations.
//
// Under the hood the Client holds a *ssh.Client plus a keepalive goroutine.
// When an operation discovers the connection is gone it returns the transport
// error and drops the connection; the next operation dials once automatically.
type Client struct {
	cfg ClientConfig

	// opMu serializes operations so at most one command runs at a time and
	// connection teardown never races a running command.
	opMu sync.Mutex

	// mu guards conn / connDead / stopKA / kaDone / closed.
	mu       sync.Mutex
	conn     *ssh.Client
	connDead chan struct{} // closed when the current conn's Wait() returns
	stopKA   chan struct{} // closed to ask the keepalive goroutine to exit
	kaDone   chan struct{} // closed when the keepalive goroutine exits
	closed   bool
}

// Dial resolves cfg defaults, dials and authenticates the SSH connection
// (md.sh `ssh ${SSH_OPTS[@]} ...` equivalent) and returns a ready Client.
//
// The returned error follows the package error contract: ErrAuthFailed for
// key/credential problems, ErrConnFailed for dial/handshake problems.
func Dial(ctx context.Context, cfg ClientConfig) (*Client, error) {
	resolved, err := resolveConfig(cfg)
	if err != nil {
		return nil, err
	}
	c := &Client{cfg: resolved}
	if err := c.connect(ctx); err != nil {
		return nil, err
	}
	return c, nil
}

// resolveConfig fills zero-valued ClientConfig fields with the md.sh-aligned
// defaults and validates the target.
func resolveConfig(cfg ClientConfig) (ClientConfig, error) {
	if cfg.Host == "" {
		return ClientConfig{}, fmt.Errorf("%w: empty host (set ClientConfig.Host)", ErrConnFailed)
	}
	if cfg.User == "" {
		cfg.User = defaultUser()
	}
	if cfg.User == "" {
		return ClientConfig{}, fmt.Errorf("%w: cannot determine ssh user (set ClientConfig.User)", ErrAuthFailed)
	}
	if cfg.Port == 0 {
		cfg.Port = 22
	}
	if cfg.KeyPath == "" {
		kp, err := defaultKeyPath()
		if err != nil {
			return ClientConfig{}, err
		}
		cfg.KeyPath = kp
	}
	if cfg.DialTimeout == 0 {
		cfg.DialTimeout = 2 * time.Second // ConnectTimeout=2
	}
	if cfg.HandshakeTimeout == 0 {
		cfg.HandshakeTimeout = 5 * time.Second
	}
	if cfg.KeepAliveInterval == 0 {
		cfg.KeepAliveInterval = 2 * time.Second // ServerAliveInterval=2
	}
	if cfg.KeepAliveCountMax == 0 {
		cfg.KeepAliveCountMax = 2 // ServerAliveCountMax=2
	}
	if cfg.HostKeyCallback == nil {
		cfg.HostKeyCallback = ssh.InsecureIgnoreHostKey()
	}
	return cfg, nil
}

// defaultUser mirrors md.sh's reliance on $USER (the Bash tool never hard
// codes the remote user for SOC2 / mini commands).
func defaultUser() string {
	if u := os.Getenv("USER"); u != "" {
		return u
	}
	if u, err := user.Current(); err == nil && u.Username != "" {
		return u.Username
	}
	return ""
}

// connect establishes the TCP + SSH connection for c. It applies the
// DialTimeout to the TCP dial and the HandshakeTimeout to the key exchange /
// authentication phase (SetDeadline before ssh.NewClientConn, cleared on
// success), then starts the dead-link watcher and the keepalive goroutine.
func (c *Client) connect(ctx context.Context) error {
	signer, err := loadSigner(c.cfg.KeyPath)
	if err != nil {
		return err
	}
	addr := net.JoinHostPort(c.cfg.Host, strconv.Itoa(c.cfg.Port))
	d := net.Dialer{Timeout: c.cfg.DialTimeout}
	raw, err := d.DialContext(ctx, "tcp", addr)
	if err != nil {
		return classifyDialError(err, addr)
	}

	if c.cfg.HandshakeTimeout > 0 {
		_ = raw.SetDeadline(time.Now().Add(c.cfg.HandshakeTimeout))
	}
	sshCfg := &ssh.ClientConfig{
		User:            c.cfg.User,
		Auth:            []ssh.AuthMethod{ssh.PublicKeys(signer)},
		HostKeyCallback: c.cfg.HostKeyCallback,
		Timeout:         c.cfg.DialTimeout,
	}
	conn, chans, reqs, err := ssh.NewClientConn(raw, addr, sshCfg)
	if err != nil {
		_ = raw.Close()
		return classifyDialError(err, addr)
	}
	_ = raw.SetDeadline(time.Time{}) // handshake done; clear the deadline
	client := ssh.NewClient(conn, chans, reqs)

	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		_ = client.Close()
		return fmt.Errorf("%w: client closed while dialing", ErrConnFailed)
	}
	c.conn = client
	c.connDead = make(chan struct{})
	c.stopKA = make(chan struct{})
	c.kaDone = make(chan struct{})
	dead := c.connDead
	stop := c.stopKA
	done := c.kaDone
	interval := c.cfg.KeepAliveInterval
	countMax := c.cfg.KeepAliveCountMax

	// Dead-link watcher: x/crypto's Conn.Wait returns when the connection
	// shuts down for any reason (remote close, keepalive drop, our Close).
	go func() {
		_ = client.Wait()
		close(dead)
	}()
	if interval > 0 {
		go keepaliveLoop(client, stop, done, interval, countMax)
	} else {
		close(done)
	}
	return nil
}

// acquire returns the current live connection, dialing once if there is none
// or if the previous one is already known-dead. It never retries the
// operation itself: a failure on the returned connection is reported to the
// caller and the connection is dropped, so the NEXT operation dials again —
// this is the dead→redial-once guarantee.
func (c *Client) acquire(ctx context.Context) (*ssh.Client, <-chan struct{}, error) {
	c.mu.Lock()
	if c.closed {
		c.mu.Unlock()
		return nil, nil, fmt.Errorf("%w: client is closed", ErrConnFailed)
	}
	conn := c.conn
	dead := c.connDead
	c.mu.Unlock()

	if conn == nil {
		if err := c.connect(ctx); err != nil {
			return nil, nil, err
		}
		c.mu.Lock()
		conn, dead = c.conn, c.connDead
		c.mu.Unlock()
		return conn, dead, nil
	}

	// The connection object still exists but may already be dead (keepalive
	// dropped it or the server closed it between operations). Non-blocking
	// probe; a healthy connection falls straight through.
	select {
	case <-dead:
		c.dropConn()
		if err := c.connect(ctx); err != nil {
			return nil, nil, err
		}
		c.mu.Lock()
		conn, dead = c.conn, c.connDead
		c.mu.Unlock()
	default:
	}
	return conn, dead, nil
}

// dropConn closes the current connection and forgets it. It is idempotent and
// safe to call from the ctx-timeout watcher goroutines of in-flight
// operations (those hold opMu, dropConn only takes mu).
func (c *Client) dropConn() {
	c.mu.Lock()
	if c.conn == nil {
		c.mu.Unlock()
		return
	}
	if c.stopKA != nil {
		close(c.stopKA)
	}
	conn := c.conn
	c.conn = nil
	c.connDead = nil
	c.stopKA = nil
	c.mu.Unlock()
	_ = conn.Close() // unblocks Wait(); keepalive goroutine exits on its own
}

// Close shuts down the pooled connection and prevents further redials.
// In-flight operations fail fast once the transport goes away.
func (c *Client) Close() error {
	c.mu.Lock()
	c.closed = true
	c.mu.Unlock()
	c.dropConn()
	return nil
}

// SSHClient exposes the underlying x/crypto connection for consumers that
// need the raw *ssh.Client — the transfer package's NewSFTPTransport. It
// returns nil after Close or while the client is between connections (call an
// op such as Exec first if a live connection is required).
func (c *Client) SSHClient() *ssh.Client {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		return nil
	}
	return c.conn
}

// runOnConn acquires a connection and runs fn on it, then applies the error
// contract: nil stays nil; a remote non-zero exit is already normalized away
// by the caller of fn (Exec) or converted to ExitError (Stream); everything
// else is a transport-layer failure.
//
// Dead→redial-once: when fn failed BEFORE the remote command could start
// (session/channel setup, exec request) the pooled connection may be stale
// (the server dropped it between operations), so the whole op is retried once
// on a freshly dialed connection. Failures after the command started are
// never retried — a retry could double-run something like `reboot`.
func (c *Client) runOnConn(ctx context.Context, fn func(*ssh.Client) error) error {
	conn, dead, err := c.acquire(ctx)
	if err != nil {
		return err
	}
	opErr := fn(conn)

	// Normalize the outcome, retrying at most once on a pre-start failure.
	for attempt := 0; ; attempt++ {
		// nil and *ExitError (Stream reports remote exits this way) are
		// results, not transport failures.
		var exitErr *ExitError
		if opErr == nil || errors.As(opErr, &exitErr) {
			return opErr
		}
		// A context timeout/cancel is reported as the context error; the
		// operation watcher has already torn the connection down so the
		// remote command dies (the ^C equivalent).
		if ctx.Err() != nil {
			c.dropConn()
			if errors.Is(opErr, ctx.Err()) {
				return opErr
			}
			return fmt.Errorf("%w: %v", ctx.Err(), opErr)
		}
		// Dead→redial-once: a failure before the command started may be a
		// stale pooled connection (server dropped it between ops). Retry the
		// whole operation once on a fresh connection; a second pre-start
		// failure is reported as-is.
		if attempt == 0 && isPreStart(opErr) {
			c.dropConn()
			conn, dead, err = c.acquire(ctx)
			if err != nil {
				return err
			}
			opErr = fn(conn)
			continue
		}
		// Post-start transport failure: surface it and drop the connection so
		// the NEXT operation dials fresh.
		if connClosed(dead) {
			c.dropConn()
		}
		return fmt.Errorf("%w: %v", ErrConnFailed, opErr)
	}
}

// connClosed reports whether the connection's Wait has returned (remote
// closed it, keepalive dropped it, or Close() was called).
func connClosed(dead <-chan struct{}) bool {
	select {
	case <-dead:
		return true
	default:
		return false
	}
}

// Ping probes reachability over the pooled connection, mirroring md.sh's
// `ssh ... exit` checks (md.sh:324, md.sh:461). A pure-Go client is
// inherently non-interactive (BatchMode), so a Ping can never block on a
// password prompt. It only reports reachable / not reachable: nil means the
// probe command ran on a live connection, any non-nil error means the target
// is not usable.
func (c *Client) Ping(ctx context.Context) error {
	pingCtx := ctx
	if _, hasDeadline := ctx.Deadline(); !hasDeadline {
		var cancel context.CancelFunc
		pingCtx, cancel = context.WithTimeout(ctx, defaultPingTimeout)
		defer cancel()
	}
	res, err := c.Exec(pingCtx, ExecRequest{Command: "exit"})
	if err != nil {
		return err
	}
	if res.ExitCode != 0 {
		return fmt.Errorf("%w: probe command exited with %d", ErrConnFailed, res.ExitCode)
	}
	return nil
}
