package tui

import (
	"context"
	"sort"
	"strings"

	"github.com/charmbracelet/bubbles/help"
	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// exportPicker is the Bubble Tea model replacing md.sh's `sys::export` fzf
// multi-select (md.sh:605-620). It lists the scanned data-root entries, lets
// the operator multi-select with Tab, select all with Ctrl-A, then confirm
// with Enter (returns the selected items) or cancel with Esc/q (returns none).
//
// It is intentionally thin: the caller passes the already-scanned candidate
// list; this model only manages cursor/selection and returns the picked
// relative paths. The actual export push stays in internal/export.
type exportPicker struct {
	ctx   context.Context
	items []string // relative paths from ScanDataRoot, already sorted
	cur   int
	sel   map[int]bool
	keys  exportPickerKeys
	help  help.Model
}

// exportPickerKeys defines the export-picker key bindings.
type exportPickerKeys struct {
	Tab       key.Binding
	CtrlA     key.Binding
	Enter     key.Binding
	ArrowUp   key.Binding
	ArrowDown key.Binding
	Quit      key.Binding
}

func defaultExportPickerKeys() exportPickerKeys {
	return exportPickerKeys{
		Tab:       key.NewBinding(key.WithKeys("tab"), key.WithHelp("Tab", "勾选")),
		CtrlA:     key.NewBinding(key.WithKeys("ctrl+a"), key.WithHelp("Ctrl-A", "全选/取消全选")),
		Enter:     key.NewBinding(key.WithKeys("enter"), key.WithHelp("Enter", "确认并导出")),
		ArrowUp:   key.NewBinding(key.WithKeys("up"), key.WithHelp("↑", "上移")),
		ArrowDown: key.NewBinding(key.WithKeys("down"), key.WithHelp("↓", "下移")),
		Quit:      key.NewBinding(key.WithKeys("esc", "q"), key.WithHelp("Esc/q", "取消")),
	}
}

func newExportPicker(ctx context.Context, items []string) *exportPicker {
	return &exportPicker{
		ctx:   ctx,
		items: items,
		sel:   make(map[int]bool),
		keys:  defaultExportPickerKeys(),
		help:  help.New(),
	}
}

// RunExportPicker opens the export-picker TUI and returns the operator's
// selected relative paths, or nil on cancel (Esc/q). It mirrors md.sh's "已取消
// 操作" return when selection is empty.
func RunExportPicker(ctx context.Context, items []string) ([]string, error) {
	m := newExportPicker(ctx, items)
	prog := tea.NewProgram(m, tea.WithContext(ctx), tea.WithAltScreen())
	final, err := prog.Run()
	if err != nil {
		return nil, err
	}
	if fm, ok := final.(*exportPicker); ok {
		return fm.selected(), nil
	}
	return nil, nil
}

// --- Bubble Tea lifecycle ---

func (m *exportPicker) Init() tea.Cmd { return nil }

func (m *exportPicker) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		return m.updateKey(msg)
	case tea.WindowSizeMsg:
		m.help.Width = msg.Width
		return m, nil
	}
	return m, nil
}

func (m *exportPicker) View() string {
	var b strings.Builder
	for i, p := range m.items {
		line := "  " + p
		if m.sel[i] {
			line = "● " + p
		} else if i == m.cur {
			line = "▸ " + p
		}
		if i == m.cur {
			line = lipgloss.NewStyle().Reverse(true).Render(line)
		}
		b.WriteString(line + "\n")
	}
	b.WriteString("\n")
	b.WriteString(m.keysHelp())
	return b.String()
}

// --- update helpers ---

func (m *exportPicker) updateKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch {
	case key.Matches(msg, m.keys.Quit):
		// Cancel: clear all selections so selected() returns nil.
		m.sel = make(map[int]bool)
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
	case key.Matches(msg, m.keys.CtrlA):
		m.toggleAll()
		return m, nil
	case key.Matches(msg, m.keys.Enter):
		return m, tea.Quit
	}
	return m, nil
}

func (m *exportPicker) move(delta int) {
	if len(m.items) == 0 {
		return
	}
	m.cur += delta
	if m.cur < 0 {
		m.cur = len(m.items) - 1
	}
	if m.cur >= len(m.items) {
		m.cur = 0
	}
}

func (m *exportPicker) toggle() {
	if len(m.items) == 0 {
		return
	}
	m.sel[m.cur] = !m.sel[m.cur]
	m.move(1)
}

func (m *exportPicker) toggleAll() {
	if len(m.items) == 0 {
		return
	}
	// If everything is already selected, clear all; else select everything.
	all := true
	for i := range m.items {
		if !m.sel[i] {
			all = false
			break
		}
	}
	m.sel = make(map[int]bool)
	if !all {
		for i := range m.items {
			m.sel[i] = true
		}
	}
}

// selected returns the picked relative paths in list order (Bash processes
// them top-to-bottom), or nil when nothings is selected / cancelled.
func (m *exportPicker) selected() []string {
	var idx []int
	for i, on := range m.sel {
		if on {
			idx = append(idx, i)
		}
	}
	if len(idx) == 0 {
		return nil
	}
	sort.Ints(idx)
	var out []string
	for _, i := range idx {
		out = append(out, m.items[i])
	}
	return out
}

func (m *exportPicker) keysHelp() string {
	var parts []string
	for _, b := range []key.Binding{m.keys.Tab, m.keys.CtrlA, m.keys.Enter, m.keys.Quit} {
		parts = append(parts, b.Help().Key+":"+b.Help().Desc)
	}
	return "  " + strings.Join(parts, "  ") + "\n"
}
