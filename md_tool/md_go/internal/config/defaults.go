package config

import (
	"os"
	"strconv"
)

const (
	DefaultSOC1IP              = "192.168.10.2"
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

// SOCID is the logical identity of the current host (md.sh's "which soi am I").
// It mirrors the mgbe3_0-IP membership gauge in startup_orin.sh.
type SOCID string

const (
	SOC1 SOCID = "soc1"
	SOC2 SOCID = "soc2"
	// SOCExternal is a host that is neither soc (a PC / x86 container / CI).
	SOCExternal SOCID = "external"
)

type Config struct {
	SOC1IP              string
	SOC2IP              string
	ServerIP            string
	MountRoot           string
	BagRoot             string
	TagExportRoot       string
	MDriveExportRoot    string
	MDriveDataRoot      string
	MDriveCache         string
	MaxRecordLagSeconds int
	// SOCID is the current host identity. Empty means "detect from network".
	SOCID SOCID
}

func Default() Config {
	return Config{
		SOC1IP:              DefaultSOC1IP,
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
	cfg.SOC1IP = envOrDefault("MDRIVE_SOC1_IP", cfg.SOC1IP)
	cfg.SOC2IP = envOrDefault("MDRIVE_SOC2_IP", cfg.SOC2IP)
	cfg.ServerIP = envOrDefault("MDRIVE_SERVER_IP", cfg.ServerIP)
	cfg.MountRoot = envOrDefault("MDRIVE_MOUNT_ROOT", cfg.MountRoot)
	cfg.BagRoot = envOrDefault("MDRIVE_TAG_BAG_ROOT", cfg.BagRoot)
	cfg.TagExportRoot = envOrDefault("MDRIVE_TAG_EXPORT_ROOT", cfg.TagExportRoot)
	cfg.MDriveExportRoot = envOrDefault("MDRIVE_EXPORT_ROOT", cfg.MDriveExportRoot)
	cfg.MDriveDataRoot = envOrDefault("MDRIVE_DATA_ROOT", cfg.MDriveDataRoot)
	cfg.MDriveCache = envOrDefault("MDRIVE_CACHE", cfg.MDriveCache)
	cfg.SOCID = SOCID(envOrDefault("MDRIVE_SOC_ID", string(cfg.SOCID)))

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
