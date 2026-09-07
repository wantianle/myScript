package tui

import (
	"context"
	"reflect"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

// update drives the picker through a sequence of key messages by calling its
// Update method directly (no tea.Program, which would try to open /dev/tty in
// a test environment).
func update(t *testing.T, m *exportPicker, keys ...tea.KeyMsg) *exportPicker {
	t.Helper()
	cur := tea.Model(m)
	for _, k := range keys {
		next, _ := cur.Update(k)
		cur = next
	}
	nm, ok := cur.(*exportPicker)
	if !ok {
		t.Fatalf("model not *exportPicker after update: %T", cur)
	}
	return nm
}

func newTestPicker() *exportPicker {
	return newExportPicker(context.Background(), []string{"a/b", "c/d", "e/f"})
}

func TestExportPickerToggleAndConfirm(t *testing.T) {
	// Tab toggles the cursor row AND advances the cursor by one (md.sh fzf
	// --multi behaviour). Start at index 0 → down to 1 ("c/d") → tab selects
	// 1 and advances to 2 ("e/f") → tab selects 2. Result: {1,2} = [c/d e/f].
	m := update(t, newTestPicker(),
		tea.KeyMsg{Type: tea.KeyDown},  // cursor 0 -> 1 ("c/d")
		tea.KeyMsg{Type: tea.KeyTab},   // select 1, cursor -> 2 ("e/f")
		tea.KeyMsg{Type: tea.KeyTab},   // select 2
		tea.KeyMsg{Type: tea.KeyEnter}, // confirm (no selection change)
	)
	got := m.selected()
	want := []string{"c/d", "e/f"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("selected() = %v, want %v", got, want)
	}
}

func TestExportPickerCtrlASelectsAll(t *testing.T) {
	m := update(t, newTestPicker(), tea.KeyMsg{Type: tea.KeyCtrlA})
	got := m.selected()
	want := []string{"a/b", "c/d", "e/f"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ctrl-a selected() = %v, want %v", got, want)
	}
}

func TestExportPickerCtrlAToggleOff(t *testing.T) {
	m := update(t, newTestPicker(),
		tea.KeyMsg{Type: tea.KeyCtrlA}, // select all
		tea.KeyMsg{Type: tea.KeyCtrlA}, // toggle off
	)
	if got := m.selected(); got != nil {
		t.Errorf("ctrl-a toggle-off should yield nil, got %v", got)
	}
}

func TestExportPickerEscCancels(t *testing.T) {
	m := update(t, newTestPicker(),
		tea.KeyMsg{Type: tea.KeyTab},  // select current "a/b"
		tea.KeyMsg{Type: tea.KeyEsc},  // cancel -> clear selection
	)
	if got := m.selected(); got != nil {
		t.Errorf("esc cancel should yield nil, got %v", got)
	}
}

func TestExportPickerEnterNoSelection(t *testing.T) {
	m := update(t, newTestPicker(), tea.KeyMsg{Type: tea.KeyEnter})
	if got := m.selected(); got != nil {
		t.Errorf("enter with no selection should yield nil, got %v", got)
	}
}
