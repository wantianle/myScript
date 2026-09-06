package config

import (
	"os"
	"strconv"
)

const (
	DefaultSOC2IP              = "192.168.10.3"
	DefaultServerIP            = "ad.minieye.tech"
	DefaultMountRoot           = "/media/data"
	DefaultBagRoot             = "/mdrive_data/bag"
	DefaultTagExportRoot       = "/media/tag_export"
	DefaultMDriveExportRoot    = "/media/mdrive_export"
	DefaultMDriveDataRoot      = "/mdrive_data"
	DefaultMDriveCache         = "/mdrive/.cache"
	DefaultMaxRecordLagSeconds = 60
)

type Config struct {
	SOC2IP              string
	ServerIP            string
	MountRoot           string
	BagRoot             string
	TagExportRoot       string
	MDriveExportRoot    string
	MDriveDataRoot      string
	MDriveCache         string
	MaxRecordLagSeconds int
}

func Default() Config {
	return Config{
		SOC2IP:              DefaultSOC2IP,
		ServerIP:            DefaultServerIP,
		MountRoot:           DefaultMountRoot,
		BagRoot:             DefaultBagRoot,
		TagExportRoot:       DefaultTagExportRoot,
		MDriveExportRoot:    DefaultMDriveExportRoot,
		MDriveDataRoot:      DefaultMDriveDataRoot,
		MDriveCache:         DefaultMDriveCache,
		MaxRecordLagSeconds: DefaultMaxRecordLagSeconds,
	}
}

func FromEnv() Config {
	cfg := Default()
	cfg.SOC2IP = envOrDefault("MDRIVE_SOC2_IP", cfg.SOC2IP)
	cfg.ServerIP = envOrDefault("MDRIVE_SERVER_IP", cfg.ServerIP)
	cfg.MountRoot = envOrDefault("MDRIVE_MOUNT_ROOT", cfg.MountRoot)
	cfg.BagRoot = envOrDefault("MDRIVE_TAG_BAG_ROOT", cfg.BagRoot)
	cfg.TagExportRoot = envOrDefault("MDRIVE_TAG_EXPORT_ROOT", cfg.TagExportRoot)
	cfg.MDriveExportRoot = envOrDefault("MDRIVE_EXPORT_ROOT", cfg.MDriveExportRoot)
	cfg.MDriveDataRoot = envOrDefault("MDRIVE_DATA_ROOT", cfg.MDriveDataRoot)
	cfg.MDriveCache = envOrDefault("MDRIVE_CACHE", cfg.MDriveCache)

	if raw := os.Getenv("MDRIVE_MAX_RECORD_LAG_SECONDS"); raw != "" {
		if value, err := strconv.Atoi(raw); err == nil && value > 0 {
			cfg.MaxRecordLagSeconds = value
		}
	}

	return cfg
}

func envOrDefault(key string, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
