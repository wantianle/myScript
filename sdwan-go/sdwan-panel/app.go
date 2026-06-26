package main

import (
	"context"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"sdwan-panel/core"
)

// App serves as the bridge between the Wails frontend and the
// SD-WAN core manager.
type App struct {
	ctx     context.Context
	manager *core.SdwanManager
}

func NewApp() *App {
	return &App{
		manager: core.GetManager(),
	}
}

// startup is called by Wails when the application starts.
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
}

// --- Exported methods (called from frontend JS) ----------------------------

func (a *App) GetStatus() map[string]interface{} {
	return a.manager.GetStatus()
}

func (a *App) GetServers() []map[string]string {
	return a.manager.GetServers()
}

func (a *App) ToggleConnection() bool {
	return a.manager.ToggleConnection()
}

func (a *App) SelectServer(id string) bool {
	return a.manager.SelectServer(id)
}

func (a *App) EditConfig() {
	_ = a.manager.EditConfig()
}

func (a *App) Reload() bool {
	return a.manager.Reload()
}

func (a *App) HidePanel() {
	if a.ctx != nil {
		runtime.WindowHide(a.ctx)
	}
}

func (a *App) Shutdown() {
	a.manager.Shutdown()
}
