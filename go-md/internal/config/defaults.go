package config

import (
	"os"
	"strconv"
)

const (
	DefaultSOC2IP              = "192.168.10.3"
	DefaultMountRoot           = "/media/data"
	DefaultBagRoot             = "/mdrive_data/bag"
	DefaultTagExportRoot       = "/media/tag_export"
	DefaultMDriveExportRoot    = "/media/mdrive_export"
	DefaultMaxRecordLagSeconds = 60
)

type Config struct {
	SOC2IP              string
	MountRoot           string
	BagRoot             string
	TagExportRoot       string
	MDriveExportRoot    string
	MaxRecordLagSeconds int
}

func Default() Config {
	return Config{
		SOC2IP:              DefaultSOC2IP,
		MountRoot:           DefaultMountRoot,
		BagRoot:             DefaultBagRoot,
		TagExportRoot:       DefaultTagExportRoot,
		MDriveExportRoot:    DefaultMDriveExportRoot,
		MaxRecordLagSeconds: DefaultMaxRecordLagSeconds,
	}
}

func FromEnv() Config {
	cfg := Default()
	cfg.SOC2IP = envOrDefault("MDRIVE_SOC2_IP", cfg.SOC2IP)
	cfg.MountRoot = envOrDefault("MDRIVE_MOUNT_ROOT", cfg.MountRoot)
	cfg.BagRoot = envOrDefault("MDRIVE_TAG_BAG_ROOT", cfg.BagRoot)
	cfg.TagExportRoot = envOrDefault("MDRIVE_TAG_EXPORT_ROOT", cfg.TagExportRoot)
	cfg.MDriveExportRoot = envOrDefault("MDRIVE_EXPORT_ROOT", cfg.MDriveExportRoot)

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
