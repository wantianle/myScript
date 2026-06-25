package main

import (
	"log"
	"os"
	"path/filepath"
)

var (
	config    *Config
	mgr       *ProcessManager
	menuState *MenuState
	exitCh    = make(chan struct{})
)

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.Lshortfile)

	// Determine the executable directory
	exe, err := os.Executable()
	if err != nil {
		log.Fatalf("Failed to get executable path: %v", err)
	}
	exeDir := filepath.Dir(exe)

	// Paths
	configPath := filepath.Join(exeDir, "iwan.conf")
	exePath := filepath.Join(exeDir, "sdwan-windows-amd64.exe")

	// 1. Load config from iwan.conf
	cfg, err := LoadConfig(configPath)
	if err != nil {
		log.Printf("Warning: Could not load config: %v, using defaults", err)
		cfg = &Config{
			Server:   ServerList[0],
			Port:     "10010",
			MTU:      "1436",
			Encrypt:  "0",
			RouteNet: "192.168.0.0/16",
			TUNName:  "iwan1",
		}
	}
	config = cfg

	// 2. Initialize process manager
	mgr = NewProcessManager(exePath)

	// 3. Start sdwan.exe subprocess
	if err := mgr.Start(); err != nil {
		log.Printf("Warning: Could not start sdwan.exe: %v", err)
	}

	// 4. Initialize menu state
	menuState = &MenuState{
		connected: mgr.IsRunning(),
		latencies: make(map[string]int64),
	}

	// Run onReady logic inline
	onReady()

	// 5. Run the raw Win32 message loop (blocks until quit)
	iconData := generateIcon()
	exitCode := RunMessageLoop(iconData)

	// 6. onExit cleanup
	onExit()

	os.Exit(exitCode)
}

func onReady() {
	// 5. Start config file watcher (restart sdwan on change, don't quit tray)
	exe, _ := os.Executable()
	configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
	go WatchConfig(configPath, func() {
		log.Println("Config changed, reloading...")
		newCfg, err := LoadConfig(configPath)
		if err != nil {
			log.Printf("Error reloading config: %v", err)
			return
		}
		config = newCfg
		if mgr != nil {
			mgr.Restart()
		}
		menuState.mu.Lock()
		menuState.connected = mgr != nil && mgr.IsRunning()
		menuState.mu.Unlock()

		// Refresh popup if visible
		onPopupRefresh()
	})

	// 6. Start latency checker goroutine
	go StartLatencyChecker(func(results map[string]int64) {
		menuState.mu.Lock()
		menuState.latencies = results
		menuState.mu.Unlock()
		onPopupRefresh()
	})
}

// onPopupRefresh refreshes the currently visible popup window.
func onPopupRefresh() {
	if globalPopup != nil {
		globalPopup.Refresh(menuState)
	}
}

func onExit() {
	// Kill sdwan.exe subprocess
	if mgr != nil && mgr.IsRunning() {
		if err := mgr.Stop(); err != nil {
			log.Printf("Error stopping sdwan.exe: %v", err)
		}
	}
	// Close popup if still open
	if globalPopup != nil {
		globalPopup.Hide()
	}
	log.Println("SDWAN Tray exiting")
}
