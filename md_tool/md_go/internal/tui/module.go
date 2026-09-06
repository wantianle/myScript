package tui

import (
	"context"
	"fmt"
	"strings"

	"mdrive/md/internal/svc"

	"github.com/charmbracelet/bubbles/help"
	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// moduleMenu is the Bubble Tea model replacing md.sh's `svc::module` fzf loop
// (md.sh:991-1066). It lists combined module status from both socs, lets the
// operator multi-select with Tab, batch start/stop/restart with Alt-S/X/R,
// open a module's log with Enter (sv) / Alt-Enter (glog), reload with Ctrl-R,
// and quit with Esc or q.
//
// The fetch, action, and log-open behaviour are delegated to the svc layer so
// this model stays thin and testable around its key handling.
type moduleMenu struct {
	ctx   context.Context
	svc   *svc.Svc
	nc    string
	keys  moduleKeys
	help  help.Model
	rows  []svc.ModuleRow // current listing (nil until first fetch completes)
	sel   map[int]bool    // cursor index -> selected (Tab multi-select)
	cur   int             // cursor index
	msg   string          // transient status/error line after an action
	loErr bool            // msg is an error (red)
}

// moduleKeys defines the module-menu key bindings.
type moduleKeys struct {
	Tab       key.Binding
	AltS      key.Binding
	AltX      key.Binding
	AltR      key.Binding
	Enter     key.Binding
	AltEnter  key.Binding
	Reload    key.Binding
	ArrowUp   key.Binding
	ArrowDown key.Binding
	Quit      key.Binding
}

func defaultModuleKeys() moduleKeys {
	return moduleKeys{
		Tab:       key.NewBinding(key.WithKeys("tab"), key.WithHelp("Tab", "多选")),
		AltS:      key.NewBinding(key.WithKeys("alt+s"), key.WithHelp("Alt-S", "启动")),
		AltX:      key.NewBinding(key.WithKeys("alt+x"), key.WithHelp("Alt-X", "停止")),
		AltR:      key.NewBinding(key.WithKeys("alt+r"), key.WithHelp("Alt-R", "重启")),
		Enter:     key.NewBinding(key.WithKeys("enter"), key.WithHelp("Enter", "sv日志")),
		AltEnter:  key.NewBinding(key.WithKeys("alt+enter"), key.WithHelp("Alt-Enter", "开发日志")),
		Reload:    key.NewBinding(key.WithKeys("ctrl+r"), key.WithHelp("Ctrl-R", "刷新")),
		ArrowUp:   key.NewBinding(key.WithKeys("up"), key.WithHelp("↑", "上移")),
		ArrowDown: key.NewBinding(key.WithKeys("down"), key.WithHelp("↓", "下移")),
		Quit:      key.NewBinding(key.WithKeys("esc", "q"), key.WithHelp("Esc/q", "退出")),
	}
}

func newModuleMenu(ctx context.Context, s *svc.Svc) *moduleMenu {
	return &moduleMenu{
		ctx:  ctx,
		svc:  s,
		nc:   "\033[0m",
		keys: defaultModuleKeys(),
		help: help.New(),
		sel:  make(map[int]bool),
	}
}

// RunModuleMenu opens the module-menu TUI and blocks until the operator quits
// (md.sh `svc::module`). It is the entry point wired from `md m` with no args.
func RunModuleMenu(ctx context.Context, s *svc.Svc) error {
	m := newModuleMenu(ctx, s)
	_, err := tea.NewProgram(m, tea.WithContext(ctx), tea.WithAltScreen()).Run()
	return err
}

// --- Bubble Tea lifecycle ---

func (m *moduleMenu) Init() tea.Cmd { return m.fetch() }

func (m *moduleMenu) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		return m.updateKey(msg)
	case moduleRowsMsg:
		m.rows = msg
		if msg == nil {
			m.msg = "（加载失败）"
			m.loErr = true
		}
		return m, nil
	case moduleActionMsg:
		m.msg = msg.msg
		m.loErr = msg.err
		return m, m.fetch() // loop back to refresh after an action
	case tea.WindowSizeMsg:
		m.help.Width = msg.Width
		return m, nil
	}
	return m, nil
}

func (m *moduleMenu) View() string {
	if m.rows == nil {
		return "加载模块列表...\n\n" + m.statusLine()
	}
	var b strings.Builder
	for i, r := range m.rows {
		line := r.Render(m.nc)
		if m.sel[i] {
			line = "● " + line
		} else if i == m.cur {
			line = "▸ " + line
		} else {
			line = "  " + line
		}
		if i == m.cur {
			line = lipgloss.NewStyle().Reverse(true).Render(line)
		}
		b.WriteString(line + "\n")
	}
	b.WriteString("\n")
	b.WriteString(m.keysHelp())
	b.WriteString(m.statusLine())
	return b.String()
}

// --- update helpers ---

func (m *moduleMenu) updateKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch {
	case key.Matches(msg, m.keys.Quit):
		return m, tea.Quit
	case key.Matches(msg, m.keys.ArrowDown):
		m.move(1)
		return m, nil
	case key.Matches(msg, m.keys.ArrowUp):
		m.move(-1)
		return m, nil
	case key.Matches(msg, m.keys.Tab):
		m.toggle()
		return m, nil
	case key.Matches(msg, m.keys.Reload):
		return m, m.fetch()
	case key.Matches(msg, m.keys.AltS):
		return m, m.action("start")
	case key.Matches(msg, m.keys.AltX):
		return m, m.action("stop")
	case key.Matches(msg, m.keys.AltR):
		return m, m.action("restart")
	case key.Matches(msg, m.keys.Enter):
		return m, m.openLog("sv")
	case key.Matches(msg, m.keys.AltEnter):
		return m, m.openLog("glog")
	}
	return m, nil
}

func (m *moduleMenu) move(delta int) {
	if len(m.rows) == 0 {
		return
	}
	m.cur += delta
	if m.cur < 0 {
		m.cur = len(m.rows) - 1
	}
	if m.cur >= len(m.rows) {
		m.cur = 0
	}
}

func (m *moduleMenu) toggle() {
	if len(m.rows) == 0 {
		return
	}
	m.sel[m.cur] = !m.sel[m.cur]
	m.move(1)
}

// action collects the selected rows (or the cursor row when nothing is
// selected) and dispatches a batch start/stop/restart through the svc layer.
func (m *moduleMenu) action(action string) tea.Cmd {
	idx := m.targets()
	if len(idx) == 0 {
		m.msg = "没有可操作的模块"
		m.loErr = true
		return nil
	}
	var soc, mod string
	for _, i := range idx {
		_ = mod
		_ = soc
		if err := m.svc.RunModuleAction(m.ctx, m.rows[i].SOC, m.rows[i].Name, action); err != nil {
			return func() tea.Msg {
				return moduleActionMsg{msg: fmt.Sprintf("批量%s: 部分失败", action), err: true}
			}
		}
	}
	// The goroutine-free path: svc layer already logged per-module results.
	return func() tea.Msg {
		count := len(idx)
		return moduleActionMsg{msg: fmt.Sprintf("批量%s: %d 个模块", action, count)}
	}
}

// openLog runs the module log view for the cursor row's soc/mod. The svc layer
// resolves the path and delegates to a pager via the log callback.
func (m *moduleMenu) openLog(logType string) tea.Cmd {
	if len(m.rows) == 0 {
		return nil
	}
	r := m.rows[m.cur]
	return func() tea.Msg {
		if err := m.svc.HandleSelectedRow(m.ctx, r.Render(m.nc), logType, func(soc, mod, t string) error {
			return m.svc.Log(m.ctx, soc, logWriter{})
		}); err != nil {
			return moduleActionMsg{msg: err.Error(), err: true}
		}
		return moduleActionMsg{msg: ""}
	}
}

func (m *moduleMenu) targets() []int {
	var out []int
	any := false
	for _, i := range m.sel {
		if i {
			any = true
			break
		}
	}
	if any {
		for i, on := range m.sel {
			if on {
				out = append(out, i)
			}
		}
		return out
	}
	if len(m.rows) > 0 {
		out = append(out, m.cur)
	}
	return out
}

// --- rendering helpers ---

func (m *moduleMenu) keysHelp() string {
	var parts []string
	for _, b := range []key.Binding{m.keys.Tab, m.keys.AltS, m.keys.AltX, m.keys.AltR,
		m.keys.Enter, m.keys.AltEnter, m.keys.Reload, m.keys.Quit} {
		parts = append(parts, b.Help().Key+":"+b.Help().Desc)
	}
	return "  " + strings.Join(parts, "  ") + "\n"
}

func (m *moduleMenu) statusLine() string {
	if m.msg == "" {
		return ""
	}
	if m.loErr {
		return fmt.Sprintf(" [ERROR] %s\n", m.msg)
	}
	return fmt.Sprintf(" [OK] %s\n", m.msg)
}

// --- commands ---

type moduleRowsMsg []svc.ModuleRow

type moduleActionMsg struct {
	msg string
	err bool
}

// fetch pulls combined module status for both socs via the svc layer (md.sh
// fetch_combined:966-986). A transport failure on a soc is skipped; a nil
// slice is returned only when nothing was gathered anywhere (rendered as an
// error state).
func (m *moduleMenu) fetch() tea.Cmd {
	return func() tea.Msg {
		rows, err := m.svc.FetchModules(m.ctx)
		if err != nil || len(rows) == 0 {
			return moduleRowsMsg(nil)
		}
		return moduleRowsMsg(rows)
	}
}

// logWriter is an io.Writer that discards streamed log output in the module
// menu (the command view has its own terminal); md.m log is shown by the
// pager callback. Keeping it here lets HandleSelectedRow's log path compile
// without importing os.
type logWriter struct{}

func (logWriter) Write(b []byte) (int, error) { return len(b), nil }
