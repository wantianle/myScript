package vmc

import (
	"reflect"
	"testing"
)

func TestSelectPackageByVersion(t *testing.T) {
	cases := []struct {
		name    string
		records []Record
		version string
		want    string
	}{
		{
			name:    "empty records",
			records: nil,
			version: "1.2.3",
			want:    "",
		},
		{
			// finstall awk `if (r == v) { print n; exit }` picks the first exact hit.
			name: "exact match returns first package",
			records: []Record{
				mkRec("mdrive", "1.2.3", "orin", ""),
				mkRec("mdrive_conf", "1.2.3", "orin", ""),
			},
			version: "1.2.3",
			want:    "mdrive",
		},
		{
			// A "-suffix" prefix candidate earlier must not beat a later exact hit.
			name: "exact match beats earlier prefix candidate",
			records: []Record{
				mkRec("mdrive_conf", "1.1.0-rc1", "orin", ""),
				mkRec("mdrive", "1.1.0", "orin", ""),
			},
			version: "1.1.0",
			want:    "mdrive",
		},
		{
			// awk prefix rule: `index(r, v "-") == 1 || index(r, v ".") == 1`.
			name: "dash prefix first candidate",
			records: []Record{
				mkRec("mdrive_map", "9.9", "orin", ""),
				mkRec("mdrive_conf", "1.1-rc1", "orin", ""),
				mkRec("mdrive_dep", "1.1.0", "orin", ""),
			},
			version: "1.1",
			want:    "mdrive_conf",
		},
		{
			name: "dot prefix candidate",
			records: []Record{
				mkRec("mdrive_conf", "1.1beta", "orin", ""),
				mkRec("mdrive", "1.1.5", "orin", ""),
			},
			version: "1.1",
			want:    "mdrive",
		},
		{
			// awk END fallback: `if (pref) print pref; else if (last) print last`
			// where "last" is actually the first non-empty name seen.
			name: "no exact or prefix falls back to first record",
			records: []Record{
				mkRec("mdrive", "2.0.0", "orin", ""),
				mkRec("mdrive_conf", "3.0.0", "orin", ""),
			},
			version: "9.9",
			want:    "mdrive",
		},
		{
			// awk prints the exact line's name even when empty and exits.
			name: "exact match with empty name returns empty",
			records: []Record{
				mkRec("", "1.0.0", "orin", ""),
				mkRec("mdrive", "1.0.0", "orin", ""),
			},
			version: "1.0.0",
			want:    "",
		},
		{
			// awk `if (!last) last=n` keeps assigning while n is empty, so the
			// fallback is the first record that actually has a name.
			name: "fallback skips leading empty names",
			records: []Record{
				mkRec("", "1.0.0", "orin", ""),
				mkRec("mdrive", "2.0.0", "orin", ""),
			},
			version: "9.9",
			want:    "mdrive",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := SelectPackageByVersion(tc.records, tc.version); got != tc.want {
				t.Fatalf("SelectPackageByVersion(%v, %q) = %q, want %q", tc.records, tc.version, got, tc.want)
			}
		})
	}
}

func TestMatchPackage(t *testing.T) {
	records := []Record{
		mkRec("mdrive", "1.0.0", "orin", "2024-01-01 00:00:00"),
		mkRec("mdrive_conf", "1.1.0", "orin", "2024-01-01 00:00:00"),
		mkRec("mdrive", "1.2.0", "orin_dsv", "2024-01-02 00:00:00"),
		mkRec("", "9.9.9", "orin", "2024-01-03 00:00:00"),
	}

	t.Run("exact name keeps order", func(t *testing.T) {
		got := MatchPackage(records, "mdrive")
		want := []Record{
			mkRec("mdrive", "1.0.0", "orin", "2024-01-01 00:00:00"),
			mkRec("mdrive", "1.2.0", "orin_dsv", "2024-01-02 00:00:00"),
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("MatchPackage(records, \"mdrive\") = %#v, want %#v", got, want)
		}
	})

	// rollback exact_col $4 == pkg must not blur mdrive and mdrive_conf rows.
	t.Run("mdrive does not match mdrive_conf", func(t *testing.T) {
		got := MatchPackage(records, "mdrive_conf")
		want := []Record{mkRec("mdrive_conf", "1.1.0", "orin", "2024-01-01 00:00:00")}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("MatchPackage(records, \"mdrive_conf\") = %#v, want %#v", got, want)
		}
	})

	t.Run("empty name never matches a package", func(t *testing.T) {
		if got := MatchPackage(records, "mdrive_model"); len(got) != 0 {
			t.Fatalf("MatchPackage(records, \"mdrive_model\") = %#v, want no match", got)
		}
	})
}

func TestFindCurrentVersion(t *testing.T) {
	pkgs := []Package{
		mkPkg("mdrive", "1.0.0"),
		mkPkg("mdrive_conf", "2.0.0"),
		mkPkg("mdrive", "1.5.0"),
	}

	t.Run("hit", func(t *testing.T) {
		if got, ok := FindCurrentVersion(pkgs, "mdrive"); !ok || got != "1.0.0" {
			t.Fatalf("FindCurrentVersion(pkgs, \"mdrive\") = %q, %v; want \"1.0.0\", true", got, ok)
		}
	})

	t.Run("first duplicate row wins", func(t *testing.T) {
		// Bash concatenated duplicate rows via tr -d; Go takes the first.
		if got, ok := FindCurrentVersion(pkgs, "mdrive"); !ok || got != "1.0.0" {
			t.Fatalf("FindCurrentVersion() duplicate handling = %q, %v", got, ok)
		}
	})

	t.Run("miss", func(t *testing.T) {
		if got, ok := FindCurrentVersion(pkgs, "mdrive_model"); ok || got != "" {
			t.Fatalf("FindCurrentVersion(pkgs, \"mdrive_model\") = %q, %v; want \"\", false", got, ok)
		}
	})
}

func TestLatestVersion(t *testing.T) {
	records := []Record{
		mkRec("mdrive", "1.0.0", "orin", ""),
		mkRec("mdrive", "1.1.0", "orin_dsv", ""),
		mkRec("mdrive", "2.0.0", "any", ""),
		mkRec("mdrive", "3.0.0", "windows", ""),
		mkRec("mdrive_conf", "9.9.9", "orin", ""),
		mkRec("mdrive", "1.2.0", "orin_x86", ""),
	}

	cases := []struct {
		name     string
		records  []Record
		pkg      string
		platform string
		wantVer  string
		wantOK   bool
	}{
		{
			// Default platform orin also matches orin_dsv / orin_x86 and the any
			// row; returns the LAST surviving row (tail -n 1).
			name:     "default orin filter returns last match",
			records:  records,
			pkg:      "mdrive",
			platform: "",
			wantVer:  "1.2.0",
			wantOK:   true,
		},
		{
			name:     "explicit orin_dsv filter",
			records:  records,
			pkg:      "mdrive",
			platform: "orin_dsv",
			wantVer:  "2.0.0",
			wantOK:   true,
		},
		{
			// "any" is always an accepted platform (grep -iE "$filter|any").
			name:     "any row survives every platform filter",
			records:  records,
			pkg:      "mdrive",
			platform: "windows",
			wantVer:  "3.0.0",
			wantOK:   true,
		},
		{
			name:     "platform keyword inside version counts as hit",
			records:  []Record{mkRec("mdrive", "1.0.0-orin", "x86", "")},
			pkg:      "mdrive",
			platform: "orin",
			wantVer:  "1.0.0-orin",
			wantOK:   true,
		},
		{
			// grep -iE runs over the whole rendered line, not just the platform
			// column, so a keyword inside the name matches too.
			name:     "platform keyword inside name counts as hit",
			records:  []Record{mkRec("mdrive_orin", "1.0.0", "x86", "")},
			pkg:      "mdrive_orin",
			platform: "orin",
			wantVer:  "1.0.0",
			wantOK:   true,
		},
		{
			// "any" is matched case-insensitively as a substring anywhere.
			name:     "any inside version matches",
			records:  []Record{mkRec("mdrive", "1.any.0", "x86", "")},
			pkg:      "mdrive",
			platform: "orin",
			wantVer:  "1.any.0",
			wantOK:   true,
		},
		{
			name:     "platform keyword case-insensitive",
			records:  records,
			pkg:      "mdrive",
			platform: "ORIN",
			wantVer:  "1.2.0",
			wantOK:   true,
		},
		{
			name:     "other package names are ignored",
			records:  records,
			pkg:      "mdrive_conf",
			platform: "",
			wantVer:  "9.9.9",
			wantOK:   true,
		},
		{
			name:     "package not present",
			records:  records,
			pkg:      "mdrive_model",
			platform: "",
			wantVer:  "",
			wantOK:   false,
		},
		{
			name:     "no record survives the platform filter",
			records:  []Record{mkRec("mdrive", "1.0.0", "orin", "")},
			pkg:      "mdrive",
			platform: "amd64",
			wantVer:  "",
			wantOK:   false,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := LatestVersion(tc.records, tc.pkg, tc.platform)
			if ok != tc.wantOK || got != tc.wantVer {
				t.Fatalf("LatestVersion(records, %q, %q) = %q, %v; want %q, %v",
					tc.pkg, tc.platform, got, ok, tc.wantVer, tc.wantOK)
			}
		})
	}
}
