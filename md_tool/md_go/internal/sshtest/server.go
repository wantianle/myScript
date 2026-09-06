// Package sshtest provides an in-process SSH + SFTP server for the sshx and
// transfer integration tests. Nothing here is used by production code.
//
// The server listens on 127.0.0.1:<random port> and:
//
//   - answers session "exec" requests by running `sh -c <command>` on the
//     local machine (the test host plays the role of the vehicle), reporting
//     the real exit status back over the channel, and
//   - answers the "sftp" subsystem with a pkg/sftp server rooted at the
//     configured working directory (default: a fresh temp dir).
//
// A client key pair is generated for every server and written to a temp file
// (mode 0600) so the sshx auth layer parses it from disk exactly like a real
// ~/.ssh/id_ed25519.
package sshtest

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/pem"
	"errors"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

// User is the ssh username tests should dial with (the in-process server does
// not care which user it is).
const User = "test"

type options struct {
	workDir    string
	rejectAuth bool
}

// Option configures a Server.
type Option func(*options)

// WithWorkingDir roots the sftp subsystem in dir instead of a fresh temp dir.
func WithWorkingDir(dir string) Option {
	return func(o *options) { o.workDir = dir }
}

// WithRejectAuth makes the server reject every public key, so clients observe
// an authentication failure during the handshake.
func WithRejectAuth() Option {
	return func(o *options) { o.rejectAuth = true }
}

// Server is one running in-process sshd.
type Server struct {
	addr    string
	workDir string
	keyPath string // client private key (PEM, 0600)
	sshConf *ssh.ClientConfig

	serverCfg *ssh.ServerConfig

	ln     net.Listener
	closed chan struct{}

	mu    sync.Mutex
	conns map[net.Conn]struct{}
}

// NewServer starts the server and registers cleanup on tb.
func NewServer(tb testing.TB, opts ...Option) *Server {
	tb.Helper()
	var o options
	for _, fn := range opts {
		fn(&o)
	}
	if o.workDir == "" {
		o.workDir = tb.TempDir()
	}
	if err := os.MkdirAll(o.workDir, 0o755); err != nil {
		tb.Fatalf("sshtest: create workdir: %v", err)
	}

	_, hostPriv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		tb.Fatalf("sshtest: host key: %v", err)
	}
	hostSigner, err := ssh.NewSignerFromKey(hostPriv)
	if err != nil {
		tb.Fatalf("sshtest: host signer: %v", err)
	}

	_, clientPriv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		tb.Fatalf("sshtest: client key: %v", err)
	}
	clientSigner, err := ssh.NewSignerFromKey(clientPriv)
	if err != nil {
		tb.Fatalf("sshtest: client signer: %v", err)
	}

	keyPath := filepath.Join(tb.TempDir(), "id_ed25519")
	if err := writePrivateKey(keyPath, clientPriv); err != nil {
		tb.Fatalf("sshtest: write client key: %v", err)
	}

	serverCfg := &ssh.ServerConfig{
		PublicKeyCallback: func(conn ssh.ConnMetadata, key ssh.PublicKey) (*ssh.Permissions, error) {
			if o.rejectAuth {
				return nil, errors.New("sshtest: auth rejected by option")
			}
			return nil, nil // 全收：any presented key is accepted
		},
	}
	serverCfg.AddHostKey(hostSigner)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		tb.Fatalf("sshtest: listen: %v", err)
	}
	s := &Server{
		addr:    ln.Addr().String(),
		workDir: o.workDir,
		keyPath: keyPath,
		sshConf: &ssh.ClientConfig{
			User:            User,
			Auth:            []ssh.AuthMethod{ssh.PublicKeys(clientSigner)},
			HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		},
		serverCfg: serverCfg,
		ln:        ln,
		closed:    make(chan struct{}),
		conns:     make(map[net.Conn]struct{}),
	}
	go s.acceptLoop()
	tb.Cleanup(s.Close)
	return s
}

// Addr returns the host:port clients should dial.
func (s *Server) Addr() string { return s.addr }

// WorkDir returns the directory the sftp subsystem is rooted at.
func (s *Server) WorkDir() string { return s.workDir }

// ClientKeyPath returns the generated client private key file, suitable for
// sshx.ClientConfig.KeyPath.
func (s *Server) ClientKeyPath() string { return s.keyPath }

// SSHConfig returns a ready-made x/crypto client config (key auth, host key
// checking off) for tests that dial the server directly, e.g. transfer tests.
func (s *Server) SSHConfig() *ssh.ClientConfig { return s.sshConf }

// Dial opens a raw x/crypto SSH connection to the server.
func (s *Server) Dial() (*ssh.Client, error) {
	return ssh.Dial("tcp", s.addr, s.sshConf)
}

// CloseConns abruptly closes every currently established SSH connection,
// simulating a server-side connection drop. The listener stays open so the
// client can redial.
func (s *Server) CloseConns() {
	s.mu.Lock()
	defer s.mu.Unlock()
	for c := range s.conns {
		_ = c.Close()
	}
	s.conns = make(map[net.Conn]struct{})
}

// Close stops the listener and closes all connections.
func (s *Server) Close() {
	select {
	case <-s.closed:
		return
	default:
		close(s.closed)
	}
	_ = s.ln.Close()
	s.mu.Lock()
	defer s.mu.Unlock()
	for c := range s.conns {
		_ = c.Close()
	}
	s.conns = make(map[net.Conn]struct{})
}

func writePrivateKey(path string, priv ed25519.PrivateKey) error {
	block, err := ssh.MarshalPrivateKey(priv, "md sshtest key")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if err := pem.Encode(f, block); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

func (s *Server) acceptLoop() {
	for {
		conn, err := s.ln.Accept()
		if err != nil {
			select {
			case <-s.closed:
				return
			default:
				continue // transient accept error; keep serving
			}
		}
		s.mu.Lock()
		s.conns[conn] = struct{}{}
		s.mu.Unlock()
		go s.handleConn(conn)
	}
}

func (s *Server) handleConn(conn net.Conn) {
	defer func() {
		_ = conn.Close()
		s.mu.Lock()
		delete(s.conns, conn)
		s.mu.Unlock()
	}()

	serverConn, chans, reqs, err := ssh.NewServerConn(conn, s.serverCfg)
	if err != nil {
		return // handshake failed (e.g. rejected auth); nothing to serve
	}
	defer serverConn.Close()
	go ssh.DiscardRequests(reqs)

	for newCh := range chans {
		if newCh.ChannelType() != "session" {
			_ = newCh.Reject(ssh.UnknownChannelType, "only session channels are supported")
			continue
		}
		ch, chReqs, err := newCh.Accept()
		if err != nil {
			continue
		}
		go s.handleSession(ch, chReqs)
	}
}

// handleSession answers one session channel: "exec" runs `sh -c` and reports
// the exit status; the "sftp" subsystem serves files rooted at workDir.
func (s *Server) handleSession(ch ssh.Channel, reqs <-chan *ssh.Request) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	type activity struct {
		name string
		done chan struct{}
	}
	var current *activity

	for req := range reqs {
		switch req.Type {
		case "exec":
			var msg struct {
				Command string
			}
			if err := ssh.Unmarshal(req.Payload, &msg); err != nil {
				if req.WantReply {
					req.Reply(false, nil)
				}
				continue
			}
			if req.WantReply {
				req.Reply(true, nil)
			}
			done := make(chan struct{})
			current = &activity{name: "exec", done: done}
			go func(command string) {
				defer close(done)
				runExec(ctx, ch, command)
			}(msg.Command)

		case "subsystem":
			var msg struct {
				Subsystem string
			}
			if err := ssh.Unmarshal(req.Payload, &msg); err != nil {
				if req.WantReply {
					req.Reply(false, nil)
				}
				continue
			}
			if msg.Subsystem != "sftp" {
				if req.WantReply {
					req.Reply(false, nil)
				}
				continue
			}
			if req.WantReply {
				req.Reply(true, nil)
			}
			done := make(chan struct{})
			current = &activity{name: "sftp", done: done}
			go func() {
				defer close(done)
				serveSFTP(ch, s.workDir)
			}()

		case "pty-req":
			// Interactive tests request a pty; accept it. No real pty is
			// allocated — the command still runs on plain pipes, which is
			// enough to exercise the ssh -t handshake.
			if req.WantReply {
				req.Reply(true, nil)
			}

		default:
			if req.WantReply {
				req.Reply(false, nil)
			}
		}
	}

	// reqs is closed: the client closed the session channel or the whole
	// connection dropped. If the activity is still running this is an early
	// teardown: cancel a running exec (kills the child) and close the channel
	// (unblocks a running sftp server). A finished exec already closed done.
	if current != nil {
		select {
		case <-current.done:
		default:
			cancel()
			_ = ch.Close()
			<-current.done
		}
	}
	_ = ch.Close()
}

// runExec runs `sh -c command` on the test host with ch as stdio and reports
// the exit status back over the channel.
func runExec(ctx context.Context, ch ssh.Channel, command string) {
	cmd := exec.CommandContext(ctx, "sh", "-c", command)
	cmd.Stdout = ch
	cmd.Stderr = ch.Stderr()

	stdin, err := cmd.StdinPipe()
	if err != nil {
		_ = ch.Close()
		return
	}
	go func() {
		// Relay the client's stdin (channel reads) to the command. When the
		// client closes its write side or the connection dies this returns
		// and closes the pipe.
		_, _ = io.Copy(stdin, ch)
		_ = stdin.Close()
	}()

	runErr := cmd.Run()
	code := 0
	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			code = exitErr.ExitCode()
			if code < 0 {
				code = 255 // killed by signal / context cancel
			}
		} else {
			code = 127 // failed to start
		}
	}
	status := struct{ Status uint32 }{uint32(code)}
	_, _ = ch.SendRequest("exit-status", false, ssh.Marshal(&status))
	_ = ch.Close()
}

// serveSFTP runs a pkg/sftp server on the session channel until the channel
// closes (client logout or connection drop).
func serveSFTP(ch ssh.Channel, workDir string) {
	sftpServer, err := sftp.NewServer(ch, sftp.WithServerWorkingDirectory(workDir))
	if err != nil {
		return
	}
	defer sftpServer.Close()
	_ = sftpServer.Serve()
	_ = ch.Close()
}
