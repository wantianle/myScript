package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"
)

// ProcessManager manages the sdwan.exe subprocess lifecycle.
type ProcessManager struct {
	cmd     *exec.Cmd
	exePath string
	running bool
	mu      sync.Mutex
}

// NewProcessManager creates a new process manager for the given executable path.
func NewProcessManager(exePath string) *ProcessManager {
	return &ProcessManager{
		exePath: exePath,
	}
}

// Start launches sdwan.exe as a non-blocking child process.
// Stdout and stderr are piped to sdwan-tray.log.
func (p *ProcessManager) Start() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		return fmt.Errorf("process already running")
	}

	// Verify executable exists
	if _, err := os.Stat(p.exePath); os.IsNotExist(err) {
		return fmt.Errorf("sdwan.exe not found at %s", p.exePath)
	}

	exeDir := filepath.Dir(p.exePath)

	// Open log file for writing
	logPath := filepath.Join(exeDir, "sdwan-tray.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		log.Printf("Warning: Could not open log file: %v", err)
	}

	p.cmd = exec.Command(p.exePath)
	p.cmd.Dir = exeDir

	if logFile != nil {
		p.cmd.Stdout = logFile
		p.cmd.Stderr = logFile
	}

	// Start non-blocking
	if err := p.cmd.Start(); err != nil {
		return fmt.Errorf("failed to start sdwan.exe: %w", err)
	}

	p.running = true
	log.Printf("Started sdwan.exe (PID: %d)", p.cmd.Process.Pid)

	// Monitor process in background
	go func() {
		err := p.cmd.Wait()
		p.mu.Lock()
		p.running = false
		p.mu.Unlock()
		if err != nil {
			log.Printf("sdwan.exe exited with error: %v", err)
		} else {
			log.Println("sdwan.exe exited normally")
		}
		if logFile != nil {
			logFile.Close()
		}
	}()

	return nil
}

// Stop terminates the sdwan.exe subprocess.
// On Windows, first tries taskkill /PID for graceful shutdown, then falls back to Kill().
func (p *ProcessManager) Stop() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.running || p.cmd == nil || p.cmd.Process == nil {
		return nil
	}

	pid := p.cmd.Process.Pid

	// Try graceful shutdown via taskkill /PID
	taskkill := exec.Command("taskkill", "/PID", fmt.Sprintf("%d", pid))
	if err := taskkill.Run(); err != nil {
		log.Printf("taskkill failed, falling back to Kill(): %v", err)
		// Fallback: force kill
		if err := p.cmd.Process.Kill(); err != nil {
			return fmt.Errorf("failed to kill process %d: %w", pid, err)
		}
	}

	p.running = false
	log.Printf("Stopped sdwan.exe (PID: %d)", pid)
	return nil
}

// Restart stops and restarts the sdwan.exe subprocess.
func (p *ProcessManager) Restart() error {
	p.Stop()
	time.Sleep(1 * time.Second)
	return p.Start()
}

// IsRunning returns whether the subprocess is currently running.
func (p *ProcessManager) IsRunning() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.running
}
