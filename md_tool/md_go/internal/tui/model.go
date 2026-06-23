package tui

import (
	"context"
	"fmt"

	"mdrive/md/internal/config"
	"mdrive/md/internal/tui/pages"

	tea "github.com/charmbracelet/bubbletea"
)

type model struct {
	cfg     config.Config
	version string
	keys    keyMap
	width   int
	height  int
}

func Run(ctx context.Context, cfg config.Config, version string) error {
	_, err := tea.NewProgram(newModel(cfg, version), tea.WithContext(ctx)).Run()
	return err
}

func newModel(cfg config.Config, version string) model {
	return model{cfg: cfg, version: version, keys: defaultKeyMap()}
}

func (m model) Init() tea.Cmd {
	return nil
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "q", "ctrl+c":
			return m, tea.Quit
		}
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
	}
	return m, nil
}

func (m model) View() string {
	body := pages.Home(pages.HomeOptions{
		Version:             m.version,
		BagRoot:             m.cfg.BagRoot,
		TagExportRoot:       m.cfg.TagExportRoot,
		MaxRecordLagSeconds: m.cfg.MaxRecordLagSeconds,
		QuitHelp:            m.keys.Quit.Help().Key + " " + m.keys.Quit.Help().Desc,
	})
	if m.width > 0 && m.height > 0 {
		body += fmt.Sprintf("\n\nterminal: %dx%d", m.width, m.height)
	}
	return appStyle.Render(body)
}
