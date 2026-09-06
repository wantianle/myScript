package health

import "testing"

func TestPercent(t *testing.T) {
	tests := []struct {
		in   string
		want int
		ok   bool
	}{
		{"42", 42, true},
		{"100", 100, true},
		{" 42%", 42, true},
		{"42%", 42, true},
		{"", 0, false},
		{"abc", 0, false},
		{"42.5", 0, false}, // md.sh expects an integer
	}
	for _, tt := range tests {
		got, ok := Percent(tt.in)
		if ok != tt.ok || (ok && got != tt.want) {
			t.Errorf("Percent(%q) = (%d,%v), want (%d,%v)", tt.in, got, ok, tt.want, tt.ok)
		}
	}
}

func TestFreeGB(t *testing.T) {
	tests := []struct {
		in   string
		want int
		ok   bool
	}{
		{"500G", 500, true},
		{"500", 500, true},
		{" 120 ", 120, true},
		{"", 0, false},
		{"abc", 0, false},
	}
	for _, tt := range tests {
		got, ok := FreeGB(tt.in)
		if ok != tt.ok || (ok && got != tt.want) {
			t.Errorf("FreeGB(%q) = (%d,%v), want (%d,%v)", tt.in, got, ok, tt.want, tt.ok)
		}
	}
}

func TestRowUsedPct(t *testing.T) {
	df := "Filesystem      Size  Used Avail Use% Mounted on\n/dev/nvme0n1p1  1.8T  400G  1.3T  24% /media/data\n"
	got, ok := RowUsedPct(df)
	if !ok || got != 24 {
		t.Fatalf("RowUsedPct = (%d,%v), want (24,true)", got, ok)
	}
}

func TestRowFreeGB(t *testing.T) {
	// df -BG output: columns are Filesystem 1B-blocks Used Available Use% Mounted on,
	// all values in single-G units.
	df := "Filesystem     1B-blocks  Used Available Use% Mounted on\n/dev/nvme0n1p1  1900G  400G     1500G  24% /media/data\n"
	got, ok := RowFreeGB(df)
	if !ok || got != 1500 {
		t.Fatalf("RowFreeGB = (%d,%v), want (1500,true)", got, ok)
	}
}

func TestRowUsedPctBad(t *testing.T) {
	if _, ok := RowUsedPct("only one line"); ok {
		t.Fatal("RowUsedPct should fail on <2 rows")
	}
	if _, ok := RowUsedPct("a b\nc d\n"); ok {
		t.Fatal("RowUsedPct should fail on <5 fields")
	}
}

func TestMounted(t *testing.T) {
	pm := "/dev/nvme0n1p1 /media/data ext4 rw,relatime 0 0\n/dev/sda1 /boot ext4 ro,relatime 0 0\n"
	if !Mounted(pm, "/media/data") {
		t.Error("Mounted should find /media/data")
	}
	if Mounted(pm, "/nope") {
		t.Error("Mounted should not find /nope")
	}
}

func TestReadOnly(t *testing.T) {
	pm := "/dev/nvme0n1p1 /media/data ext4 rw,relatime 0 0\n"
	if ReadOnly(pm, "/media/data") {
		t.Error("rw mount should not be read-only")
	}
	ro := "/dev/nvme0n1p1 /media/data ext4 ro,relatime 0 0\n"
	if !ReadOnly(ro, "/media/data") {
		t.Error("ro mount should be detected")
	}
}
