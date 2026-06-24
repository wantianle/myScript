package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const (
	defaultConfigPath = "/etc/sdwan/iwan.conf"
	defaultTUNName    = "iwan1"
	routeNetwork      = "192.168.0.0/16"
)

func main() {
	configPath := flag.String("f", defaultConfigPath, "config file path")
	flag.Parse()

	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	log.Printf("[INFO] SDWAN Go client starting, config=%s", *configPath)

	// 1. Load config
	cfg, err := LoadConfig(*configPath)
	if err != nil {
		log.Fatalf("[FATAL] Config error: %v", err)
	}
	log.Printf("[INFO] Server=%s Port=%d User=%s MTU=%d Encrypt=%d",
		cfg.Server, cfg.Port, cfg.Username, cfg.MTU, cfg.Encrypt)

	// 2. Create client
	client, err := NewClient(cfg)
	if err != nil {
		log.Fatalf("[FATAL] Create client: %v", err)
	}
	defer client.Close()

	// 3. Connect to server
	if err := client.Connect(); err != nil {
		log.Fatalf("[FATAL] UDP connect: %v", err)
	}
	log.Printf("[INFO] UDP connected to %s:%d", cfg.Server, cfg.Port)

	// 4. Handshake
	log.Println("[AUTH] Waiting for OPENACK...")
	openAck, err := client.Handshake()
	if err != nil {
		log.Fatalf("[FATAL] Handshake: %v", err)
	}
	log.Println("[AUTH] Authenticated successfully")

	// Parse TUN configuration from OPENACK
	tunCfg := ParseOPENACK(openAck)
	log.Printf("[DEBUG] OPENACK raw (%d bytes): %x", len(openAck), openAck)
	log.Printf("[DEBUG] Parsed: local=%q gateway=%q dns=%q mtu=%d",
		tunCfg.LocalIP, tunCfg.GatewayIP, tunCfg.DNSIP, tunCfg.MTU)
	if tunCfg.LocalIP == "" || tunCfg.GatewayIP == "" {
		log.Fatalf("[FATAL] OPENACK missing IP info: local=%q gateway=%q", tunCfg.LocalIP, tunCfg.GatewayIP)
	}
	log.Printf("[TUN] Local IP=%s Gateway=%s DNS=%s MTU=%d",
		tunCfg.LocalIP, tunCfg.GatewayIP, tunCfg.DNSIP, tunCfg.MTU)

	// Override config MTU if server sent one
	if tunCfg.MTU > 0 {
		cfg.MTU = int(tunCfg.MTU)
	}

	// 5. Create TUN
	tun, err := CreateTUN(defaultTUNName, cfg.MTU)
	if err != nil {
		log.Fatalf("[FATAL] Create TUN: %v", err)
	}
	client.tun = tun
	defer CloseTUN(tun, defaultTUNName)
	log.Printf("[TUN] Created %s (MTU=%d)", defaultTUNName, cfg.MTU)

	// 6. Assign IP and bring up
	if err := SetTUNIP(defaultTUNName, tunCfg.LocalIP+"/24", tunCfg.GatewayIP); err != nil {
		log.Printf("[WARN] Set TUN IP failed: %v", err)
	} else {
		log.Printf("[TUN] %s IP=%s/24 gateway=%s", defaultTUNName, tunCfg.LocalIP, tunCfg.GatewayIP)
	}

	// 7. Add route
	if err := AddRoute(routeNetwork, defaultTUNName); err != nil {
		log.Printf("[WARN] Route add failed (may need to wait): %v", err)
		// Retry after delay
		time.Sleep(3 * time.Second)
		if err := AddRoute(routeNetwork, defaultTUNName); err != nil {
			log.Printf("[WARN] Route still failed: %v", err)
		}
	}
	defer DelRoute(routeNetwork, defaultTUNName)
	log.Printf("[ROUTE] Added %s -> %s", routeNetwork, defaultTUNName)

	// 8. Handle signals for clean shutdown
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// 9. Show status
	showStatus := func() {
		fmt.Println()
		log.Println("[STATUS] SDWAN tunnel is running")
		log.Printf("  Server:  %s:%d", cfg.Server, cfg.Port)
		log.Printf("  User:    %s", cfg.Username)
		log.Printf("  Session: %d", client.sessionID)
		log.Printf("  TUN:     %s", defaultTUNName)
		log.Printf("  Route:   %s -> %s", routeNetwork, defaultTUNName)
		fmt.Println()
	}
	showStatus()

	// 10. Run main loop in background
	errCh := make(chan error, 1)
	go func() {
		errCh <- client.Run()
	}()

	// 11. Wait for signal or error
	select {
	case sig := <-sigCh:
		log.Printf("[INFO] Received signal %v, shutting down...", sig)
	case err := <-errCh:
		if err != nil {
			log.Printf("[ERROR] Client error: %v", err)
		}
	}

	log.Println("[INFO] Shutdown complete")
}
