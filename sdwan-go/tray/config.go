package main

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
)

// Config holds parsed iwan.conf settings.
type Config struct {
	Server   string
	Username string
	Password string
	Port     string
	MTU      string
	Encrypt  string
	TUNName  string
	RouteNet string
}

// ServerList returns all available servers (same as sdwan-go DefaultServers).
var ServerList = []string{
	"minieye.9966.org",
	"dwan.minieye.tech",
	"minieye.8866.org",
	"minieye.2288.org",
	"youjia.8866.org",
}

// LoadConfig parses an INI-style config file (key=value, skip # comments and [sections]).
func LoadConfig(path string) (*Config, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open config: %w", err)
	}
	defer f.Close()

	cfg := &Config{
		Port:     "10010",
		MTU:      "1436",
		Encrypt:  "0",
		RouteNet: "192.168.0.0/16",
		TUNName:  "iwan1",
	}

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// Skip empty lines, comments, and section headers
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, "[") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key := strings.TrimSpace(parts[0])
		val := strings.TrimSpace(parts[1])

		switch key {
		case "server":
			cfg.Server = val
		case "username":
			cfg.Username = val
		case "password":
			cfg.Password = val
		case "port":
			cfg.Port = val
		case "mtu":
			cfg.MTU = val
		case "encrypt":
			cfg.Encrypt = val
		case "tunname":
			cfg.TUNName = val
		case "routenet":
			cfg.RouteNet = val
		}
	}

	return cfg, nil
}

// SaveConfig writes the config back to disk in INI format.
func SaveConfig(path string, cfg *Config) error {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("create config: %w", err)
	}
	defer f.Close()

	lines := []struct {
		key, val string
	}{
		{"server", cfg.Server},
		{"username", cfg.Username},
		{"password", cfg.Password},
		{"port", cfg.Port},
		{"mtu", cfg.MTU},
		{"encrypt", cfg.Encrypt},
		{"tunname", cfg.TUNName},
		{"routenet", cfg.RouteNet},
	}

	for _, l := range lines {
		if l.val != "" {
			fmt.Fprintf(f, "%s=%s\n", l.key, l.val)
		}
	}

	return nil
}

// WatchConfig monitors the config file for changes using fsnotify.
// onChange is called after a 500ms debounce to avoid multiple rapid fires.
func WatchConfig(path string, onChange func()) {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		log.Printf("Error creating file watcher: %v", err)
		return
	}
	defer watcher.Close()

	if err := watcher.Add(path); err != nil {
		log.Printf("Error watching config file: %v", err)
		return
	}

	log.Printf("Watching config file: %s", path)

	var debounceTimer *time.Timer
	const debounceDelay = 500 * time.Millisecond

	for {
		select {
		case event, ok := <-watcher.Events:
			if !ok {
				return
			}
			if event.Op&(fsnotify.Write|fsnotify.Create) != 0 {
				if debounceTimer != nil {
					debounceTimer.Stop()
				}
				debounceTimer = time.AfterFunc(debounceDelay, func() {
					log.Println("Config file modified, triggering reload")
					onChange()
				})
			}
		case err, ok := <-watcher.Errors:
			if !ok {
				return
			}
			log.Printf("Watcher error: %v", err)
		}
	}
}
