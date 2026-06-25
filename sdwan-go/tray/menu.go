package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/getlantern/systray"
)

// MenuState holds the dynamic state for the tray menu.
type MenuState struct {
	connected bool
	latencies map[string]int64
	mu        sync.Mutex
}

// Menu items that need to be updated dynamically.
var (
	menuConnectionStatus *systray.MenuItem
	menuToggleVPN        *systray.MenuItem
	serverMenuItems      = make(map[string]*systray.MenuItem)
	serverMenu           *systray.MenuItem
)

// buildMenu creates the complete tray menu structure.
func buildMenu(state *MenuState) {
	// Connection status (disabled, shows current state)
	menuConnectionStatus = systray.AddMenuItem("⚡ 连接状态: 已断开", "")
	menuConnectionStatus.Disable()
	updateConnectionStatus(state.connected)

	systray.AddSeparator()

	// Server submenu
	serverMenu = systray.AddMenuItem("服务器线路", "选择服务器")
	buildServerSubmenu(serverMenu, state)

	systray.AddSeparator()

	// Toggle VPN
	menuToggleVPN = systray.AddMenuItem("启用 VPN", "连接或断开 VPN")
	go handleToggleVPN()

	// Edit config
	editConfigItem := systray.AddMenuItem("编辑配置文件", "用记事本打开 iwan.conf")
	go handleEditConfig(editConfigItem)

	// Reload config
	reloadConfigItem := systray.AddMenuItem("重新加载配置", "重启 SDWAN 服务")
	go handleReloadConfig(reloadConfigItem)

	systray.AddSeparator()

	// View log
	viewLogItem := systray.AddMenuItem("查看日志", "用记事本打开 sdwan-tray.log")
	go handleViewLog(viewLogItem)

	// Quit
	quitItem := systray.AddMenuItem("退出", "关闭 SDWAN Tray")
	go handleQuit(quitItem)
}

// buildServerSubmenu populates the server selection submenu.
func buildServerSubmenu(parent *systray.MenuItem, state *MenuState) {
	state.mu.Lock()
	defer state.mu.Unlock()

	for _, server := range ServerList {
		label := server
		if state.latencies != nil {
			if lat, ok := state.latencies[server]; ok && lat > 0 {
				label = formatServerLabel(server, lat)
			}
		}

		item := parent.AddSubMenuItem(label, "切换到 "+server)
		serverMenuItems[server] = item

		// Check if this is the current server
		if config != nil && config.Server == server {
			item.Check()
		}

		// Handle server selection
		go handleServerSelect(server, item)
	}
}

// updateLatencyMenu updates latency values in server submenu labels.
func updateLatencyMenu(server string, latency int64) {
	if item, ok := serverMenuItems[server]; ok {
		item.SetTitle(formatServerLabel(server, latency))
	}
}

// updateConnectionStatus updates the connection status menu item.
func updateConnectionStatus(connected bool) {
	if menuConnectionStatus != nil {
		if connected {
			menuConnectionStatus.SetTitle("⚡ 连接状态: 已连接")
		} else {
			menuConnectionStatus.SetTitle("⚡ 连接状态: 已断开")
		}
	}
	if menuToggleVPN != nil {
		if connected {
			menuToggleVPN.SetTitle("断开 VPN")
		} else {
			menuToggleVPN.SetTitle("启用 VPN")
		}
	}
}

func formatServerLabel(server string, latencyMs int64) string {
	if config != nil && config.Server == server {
		return "● " + server + " (" + formatLatency(latencyMs) + ")"
	}
	return "○ " + server + " (" + formatLatency(latencyMs) + ")"
}

func formatLatency(ms int64) string {
	if ms <= 0 {
		return "超时"
	}
	return fmt.Sprintf("%dms", ms)
}

func handleServerSelect(server string, item *systray.MenuItem) {
	for range item.ClickedCh {
		if config == nil {
			continue
		}
		config.Server = server

		// Save config
		exe, err := os.Executable()
		if err != nil {
			continue
		}
		configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
		if err := SaveConfig(configPath, config); err != nil {
			log.Printf("Error saving config: %v", err)
			continue
		}

		// Update checkmarks
		for s, mi := range serverMenuItems {
			if s == server {
				mi.Check()
			} else {
				mi.Uncheck()
			}
		}

		// Restart sdwan
		if mgr != nil {
			mgr.Restart()
		}
		menuState.connected = mgr != nil && mgr.IsRunning()
		updateConnectionStatus(menuState.connected)
	}
}

func handleToggleVPN() {
	for range menuToggleVPN.ClickedCh {
		if mgr == nil {
			continue
		}
		if mgr.IsRunning() {
			mgr.Stop()
			menuState.mu.Lock()
			menuState.connected = false
			menuState.mu.Unlock()
		} else {
			mgr.Start()
			menuState.mu.Lock()
			menuState.connected = true
			menuState.mu.Unlock()
		}
		updateConnectionStatus(menuState.connected)
	}
}

func handleEditConfig(item *systray.MenuItem) {
	for range item.ClickedCh {
		exe, err := os.Executable()
		if err != nil {
			continue
		}
		configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
		cmd := exec.Command("notepad.exe", configPath)
		cmd.Start()
	}
}

func handleReloadConfig(item *systray.MenuItem) {
	for range item.ClickedCh {
		exe, err := os.Executable()
		if err != nil {
			continue
		}
		configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
		newCfg, err := LoadConfig(configPath)
		if err != nil {
			log.Printf("Error reloading config: %v", err)
			continue
		}
		config = newCfg

		// Restart sdwan
		if mgr != nil {
			mgr.Restart()
		}
		menuState.connected = mgr != nil && mgr.IsRunning()
		updateConnectionStatus(menuState.connected)
	}
}

func handleViewLog(item *systray.MenuItem) {
	for range item.ClickedCh {
		exe, err := os.Executable()
		if err != nil {
			continue
		}
		logPath := filepath.Join(filepath.Dir(exe), "sdwan-tray.log")
		cmd := exec.Command("notepad.exe", logPath)
		cmd.Start()
	}
}

func handleQuit(item *systray.MenuItem) {
	for range item.ClickedCh {
		systray.Quit()
	}
}

// updateServerSelection syncs checkmarks with the current config server.
func updateServerSelection() {
	if config == nil {
		return
	}
	for server, item := range serverMenuItems {
		if server == config.Server {
			item.Check()
		} else {
			item.Uncheck()
		}
	}
}
