package cli

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"mdrive/md/internal/config"
	"mdrive/md/internal/export"
	"mdrive/md/internal/logx"
	"mdrive/md/internal/sshx"
	"mdrive/md/internal/transfer"

	"github.com/spf13/cobra"
)

const exportDestRoot = "/media/mdrive_export"

// exportCmd implements `md e` (md.sh sys::export :585-634). It resolves the
// export target from the SSH session (LAN direct or reverse tunnel), dials the
// target over SSH, and SFTP-pushes the selected data-root entries.
//
// The file selection and push orchestration live in internal/export and are
// unit-tested against an offline LocalDirTransport; this command wires the
// real SFTP transport.
func exportCmd(cfg config.Config, log *logx.Logger) *cobra.Command {
	return &cobra.Command{
		Use:     "export",
		Aliases: []string{"e"},
		Short:   "Export selected data content to the controlling computer",
		Args:    cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			// 1. Resolve the target (md.sh prepare_export_ssh :398-444).
			tgt, err := export.ResolveTarget(os.Getenv("SSH_CONNECTION"), export.ReverseTunnelPorts(), "")
			if err != nil {
				if err == export.ErrNoTunnel || err == export.ErrAmbiguous {
					log.Err("%v", err)
				} else {
					return err
				}
			}
			if tgt.IP == "" {
				return fmt.Errorf("未检测到本地 SSH 连接 IP")
			}

			// 2. Establish the SSH+SFTP transport to the target.
			user := os.Getenv("EXPORT_PC_USER")
			if user == "" {
				user = "mini"
			}
			port, _ := strconv.Atoi(tgt.Port)
			client, err := sshx.Dial(cmd.Context(), sshx.ClientConfig{
				User: user, Host: tgt.IP, Port: port,
				DialTimeout: 2 * time.Second, HandshakeTimeout: 5 * time.Second,
			})
			if err != nil {
				return fmt.Errorf("无法连接导出目标 %s:%s: %w", user, tgt.IP, err)
			}
			defer client.Close()
			tr, err := transfer.NewSFTPTransport(client.SSHClient())
			if err != nil {
				return err
			}
			defer tr.Close()

			// 3. Scan, allow the operator to pick, and push.
			dest := exportDestRoot + "/" + time.Now().Format("0102_1504")
			opts := export.PushOptions{
				DataRoot:  cfg.MDriveDataRoot,
				Dest:      dest,
				Tgt:       tgt,
				User:      user,
				Transport: tr,
				// Interactive (TTY) → open the export picker (md.sh's fzf
				// multi-select); scripted (non-TTY) → nil so Export selects
				// everything, mirroring `md m`'s TTY/menu vs list split.
				SelectFiles: exportPicker(cmd.Context()),
				Log: func(level, msg string) {
					switch level {
					case "err":
						log.Err("%s", msg)
					case "warn":
						log.Warn("%s", msg)
					default:
						log.Info("%s", msg)
					}
				},
			}
			failed, err := export.Export(cmd.Context(), opts)
			if err != nil {
				return err
			}
			if failed > 0 {
				return fmt.Errorf("部分文件导出失败")
			}
			log.Ok("导出完成！本地路径: %s@%s:%s", user, tgt.IP, dest)
			return nil
		},
	}
}
