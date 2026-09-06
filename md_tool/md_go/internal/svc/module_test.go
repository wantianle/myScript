package svc

import (
	"context"
	"strings"
	"testing"

	"mdrive/md/internal/config"
)

func TestParseSupervisorStatus(t *testing.T) {
	out := "Camera         RUNNING   pid 123, uptime 0:00:05\n" +
		"Teleop         RUNNING   pid 456, uptime 1:00:00\n" +
		"Dnp            STOPPED   Not started\n" +
		"display_line_ignored\n"
	rows := ParseSupervisorStatus("soc1", out)
	if len(rows) != 3 {
		t.Fatalf("ParseSupervisorStatus got %d rows, want 3: %+v", len(rows), rows)
	}
	if rows[0].SOC != "soc1" || rows[0].Name != "Camera" || rows[0].State != "RUNNING" {
		t.Errorf("row0 = %+v", rows[0])
	}
	if rows[2].State != "STOPPED" {
		t.Errorf("row2 = %+v", rows[2])
	}
}

func TestModuleRowClass(t *testing.T) {
	tests := []struct {
		row  ModuleRow
		want StatusClass
	}{
		{ModuleRow{State: "RUNNING", Tail: "pid 1, uptime 0:00:05"}, StatusStarting},
		{ModuleRow{State: "RUNNING", Tail: "pid 1, uptime 1:00:00"}, StatusRunning},
		{ModuleRow{State: "STOPPED", Tail: "Not started"}, StatusStopped},
	}
	for _, tt := range tests {
		if got := tt.row.Class(); got != tt.want {
			t.Errorf("Class(%+v) = %v, want %v", tt.row, got, tt.want)
		}
	}
}

func TestModuleRowRender(t *testing.T) {
	r := ModuleRow{SOC: "soc1", Name: "Camera", State: "RUNNING", Tail: "pid 1, uptime 1:00:00"}
	rendered := r.Render("\033[0m")
	if !strings.HasPrefix(rendered, green) {
		t.Errorf("running render should start green, got %q", rendered)
	}
	if !strings.Contains(rendered, "[soc1] Camera") {
		t.Errorf("render should contain '[soc1] Camera', got %q", rendered)
	}
}

func TestStripANSI(t *testing.T) {
	in := "\033[1;32m[soc1] Camera RUNNING pid 1\033[0m"
	got := StripANSI(in)
	if strings.Contains(got, "\033[") || !strings.Contains(got, "[soc1] Camera") {
		t.Errorf("StripANSI = %q", got)
	}
}

func TestModCtlInvalidAction(t *testing.T) {
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return &fakeShell{}, nil
	})
	if err := svc.ModCtl(context.Background(), "frob", "soc1", []string{"Camera"}); err == nil {
		t.Fatal("ModCtl should reject invalid action")
	}
}

func TestModCtlInvalidSOC(t *testing.T) {
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return &fakeShell{}, nil
	})
	if err := svc.ModCtl(context.Background(), "start", "soc3", []string{"Camera"}); err == nil {
		t.Fatal("ModCtl should reject invalid soc")
	}
}

func TestHandleSelectedRowParsesAndActions(t *testing.T) {
	fs := &fakeShell{execOuts: map[string]ExecOut{
		"sudo supervisorctl start Camera": {Code: 0},
	}}
	log, _ := bufferLog()
	svc := NewWithShell(config.Default(), log, func(soc string, ctx context.Context) (Shell, error) {
		return fs, nil
	})

	// Start action on a selected row.
	if err := svc.HandleSelectedRow(context.Background(), "\033[1;32m[soc1] Camera RUNNING pid 1\033[0m", "start", nil); err != nil {
		t.Fatalf("HandleSelectedRow(start) err = %v", err)
	}
	found := false
	for _, c := range fs.commands {
		if strings.Contains(c, "supervisorctl start Camera") {
			found = true
		}
	}
	if !found {
		t.Errorf("start action did not run supervisorctl; commands=%v", fs.commands)
	}

	// glog action invokes the log callback.
	var cbSOC, cbMod, cbType string
	if err := svc.HandleSelectedRow(context.Background(), "[soc2] Dnp STOPPED Not started", "glog", func(soc, mod, t string) error {
		cbSOC, cbMod, cbType = soc, mod, t
		return nil
	}); err != nil {
		t.Fatalf("HandleSelectedRow(glog) err = %v", err)
	}
	if cbSOC != "soc2" || cbMod != "Dnp" || cbType != "glog" {
		t.Errorf("glog callback = (%s,%s,%s)", cbSOC, cbMod, cbType)
	}
}
