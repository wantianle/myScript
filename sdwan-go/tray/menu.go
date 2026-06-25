package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
)

// MenuAction identifies the action triggered by a menu item click.
type MenuAction int

const (
	ActionStatus MenuAction = iota // disabled status line
	ActionDivider
	ActionServerGroup   // "服务器线路" — expand/collapse
	ActionSelectServer  // individual server item
	ActionToggleVPN
	ActionEditConfig
	ActionViewLog
	ActionQuit
)

// MenuItem is a flat data model for one row in the custom popup.
type MenuItem struct {
	Label    string
	Action   MenuAction
	Server   string // only for ActionSelectServer
	Disabled bool
	Selected bool
	Indented bool // sub-items indented
}

// MenuState holds the dynamic state for the tray menu.
type MenuState struct {
	connected bool
	latencies map[string]int64
	mu        sync.Mutex
}

// PopupUI bridges the popup window to the application logic.
type PopupUI struct {
	state     *MenuState
	popup     *PopupWindow
}

// BuildMenuItems returns the flat list of menu items for the popup.
func BuildMenuItems(state *MenuState) []MenuItem {
	state.mu.Lock()
	defer state.mu.Unlock()

	items := []MenuItem{}

	// Status line
	statusLabel := "SDWAN 已断开"
	if state.connected {
		statusLabel = "SDWAN 已连接"
	}
	items = append(items, MenuItem{
		Label:    statusLabel,
		Action:   ActionStatus,
		Disabled: true,
		Selected: state.connected,
	})

	items = append(items, MenuItem{Action: ActionDivider})

	// Server group header
	items = append(items, MenuItem{
		Label:  "服务器线路",
		Action: ActionServerGroup,
	})

	// Server items (rendered only when expanded in popup)
	for _, server := range ServerList {
		label := server
		if state.latencies != nil {
			if lat, ok := state.latencies[server]; ok && lat > 0 {
				label = fmt.Sprintf("%s · %dms", server, lat)
			}
		}
		isSelected := config != nil && config.Server == server
		items = append(items, MenuItem{
			Label:    label,
			Action:   ActionSelectServer,
			Server:   server,
			Indented: true,
			Selected: isSelected,
		})
	}

	items = append(items, MenuItem{Action: ActionDivider})

	// Toggle VPN
	vpnLabel := "启用 VPN"
	if state.connected {
		vpnLabel = "断开 VPN"
	}
	items = append(items, MenuItem{
		Label:  vpnLabel,
		Action: ActionToggleVPN,
	})

	items = append(items, MenuItem{Action: ActionDivider})

	// Edit config
	items = append(items, MenuItem{
		Label:  "编辑配置",
		Action: ActionEditConfig,
	})

	// View log
	items = append(items, MenuItem{
		Label:  "查看日志",
		Action: ActionViewLog,
	})

	items = append(items, MenuItem{Action: ActionDivider})

	// Quit
	items = append(items, MenuItem{
		Label:  "退出",
		Action: ActionQuit,
	})

	return items
}

// HandlePopupClick dispatches a menu item click to the appropriate handler.
func HandlePopupClick(item MenuItem) {
	switch item.Action {
	case ActionToggleVPN:
		handleToggleVPNAction()
	case ActionSelectServer:
		handleServerSelectAction(item.Server)
	case ActionEditConfig:
		handleEditConfigAction()
	case ActionViewLog:
		handleViewLogAction()
	case ActionQuit:
		handleQuitAction()
	case ActionServerGroup:
		// handled by popup expand/collapse toggle
	}
}

func handleToggleVPNAction() {
	if mgr == nil {
		return
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
}

func handleServerSelectAction(server string) {
	if config == nil {
		return
	}
	config.Server = server

	exe, err := os.Executable()
	if err != nil {
		return
	}
	configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
	if err := SaveConfig(configPath, config); err != nil {
		log.Printf("Error saving config: %v", err)
		return
	}

	if mgr != nil {
		mgr.Restart()
	}
	menuState.connected = mgr != nil && mgr.IsRunning()
}

func handleEditConfigAction() {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	configPath := filepath.Join(filepath.Dir(exe), "iwan.conf")
	cmd := exec.Command("notepad.exe", configPath)
	cmd.Start()
}

func handleViewLogAction() {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	logPath := filepath.Join(filepath.Dir(exe), "sdwan-tray.log")
	cmd := exec.Command("notepad.exe", logPath)
	cmd.Start()
}

func handleQuitAction() {
	if appHwnd != 0 {
		PostQuitMessage()
	}
}
