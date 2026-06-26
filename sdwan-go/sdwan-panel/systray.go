package main

import (
	"log"
	"os"

	"github.com/getlantern/systray"
)

// systrayShowCh signals the Wails window to show.
var systrayShowCh = make(chan struct{}, 1)

// generateTrayIcon creates a small blue circle icon PNG for the systray.
func generateTrayIcon() []byte {
	return generateTrayIconPNG()
}

// startSysTray runs the systray in the main goroutine (blocks).
func startSysTray() {
	systray.Run(onTrayReady, onTrayExit)
}

func onTrayReady() {
	systray.SetIcon(generateTrayIcon())
	systray.SetTitle("SDWAN Panel")
	systray.SetTooltip("SDWAN Panel — 右键打开菜单")

	mShow := systray.AddMenuItem("显示面板", "打开 SDWAN 控制面板")
	systray.AddSeparator()
	mQuit := systray.AddMenuItem("退出", "关闭 SDWAN Panel")

	go func() {
		for {
			select {
			case <-mShow.ClickedCh:
				select {
				case systrayShowCh <- struct{}{}:
				default:
				}
			case <-mQuit.ClickedCh:
				systray.Quit()
				return
			}
		}
	}()
}

func onTrayExit() {
	log.Println("Tray exited, shutting down...")
	os.Exit(0)
}
