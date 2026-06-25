package main

import (
	"log"
	"net"
	"time"
)

// StartLatencyChecker runs in a background goroutine, checking UDP latency
// to each server in ServerList on port 10010 every 10 seconds.
// The SDWAN protocol uses UDP, not TCP.
// Results are reported via the updateFn callback.
func StartLatencyChecker(updateFn func(results map[string]int64)) {
	const checkInterval = 10 * time.Second
	const dialTimeout = 2 * time.Second

	// Run first check immediately
	go func() {
		checkAllServers(updateFn, dialTimeout)
	}()

	ticker := time.NewTicker(checkInterval)
	defer ticker.Stop()

	for range ticker.C {
		checkAllServers(updateFn, dialTimeout)
	}
}

func checkAllServers(updateFn func(results map[string]int64), timeout time.Duration) {
	results := make(map[string]int64)

	for _, server := range ServerList {
		latency := checkSingleServer(server, timeout)
		results[server] = latency
	}

	if updateFn != nil {
		updateFn(results)
	}
}

func checkSingleServer(server string, timeout time.Duration) int64 {
	addr := net.JoinHostPort(server, "10010")

	start := time.Now()
	conn, err := net.DialTimeout("udp", addr, timeout)
	if err != nil {
		log.Printf("Latency check failed for %s: %v", server, err)
		return -1
	}
	conn.Close()

	elapsed := time.Since(start)
	ms := elapsed.Milliseconds()
	log.Printf("Latency to %s: %dms", server, ms)
	return ms
}
