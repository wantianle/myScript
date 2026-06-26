package main

import (
	"context"
	"embed"
	"log"
	"os"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
	"github.com/wailsapp/wails/v2/pkg/runtime"
	windowsOptions "github.com/wailsapp/wails/v2/pkg/options/windows"
)

//go:embed all:frontend
var assets embed.FS

// appCtx holds the Wails runtime context for window operations.
var appCtx context.Context

func main() {
	app := NewApp()

	if f, err := os.Create("sdwan-panel.log"); err == nil {
		log.SetOutput(f)
		defer f.Close()
	}
	log.Println("SDWAN Panel starting...")

	// Start systray in a separate goroutine (it blocks on its own event loop).
	go startSysTray()

	// Start a goroutine that listens for systray "show panel" signals
	// and calls WindowShow/WIndowHide via the Wails runtime.
	go func() {
		for range systrayShowCh {
			if appCtx != nil {
				runtime.WindowShow(appCtx)
				runtime.WindowSetPosition(appCtx, -1, -1) // let OS place it (bottom-right)
			}
		}
	}()

	err := wails.Run(&options.App{
		Title:       "SDWAN Panel",
		Width:       280,
		Height:      380,
		Frameless:   true,
		StartHidden: true,

		AssetServer: &assetserver.Options{
			Assets: assets,
		},

		Windows: &windowsOptions.Options{
			WebviewIsTransparent: true,
			WindowIsTranslucent:  true,
		},

		OnStartup: func(ctx context.Context) {
			appCtx = ctx
			app.startup(ctx)
		},
		OnShutdown: func(ctx context.Context) {
			app.Shutdown()
		},

		Bind: []interface{}{app},
	})

	if err != nil {
		log.Fatalf("Wails error: %v", err)
	}
}
