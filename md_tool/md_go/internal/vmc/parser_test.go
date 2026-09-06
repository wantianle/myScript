package vmc

import (
	"reflect"
	"testing"
)

// mkPkg is a shorthand for a vmc list row.
func mkPkg(name, version string) Package {
	return Package{Name: name, Version: version}
}

// mkRec is a shorthand for a fsearch record.
func mkRec(name, version, platform, releaseTime string) Record {
	return Record{Name: name, Version: version, Platform: platform, ReleaseTime: releaseTime}
}

func TestParseList(t *testing.T) {
	cases := []struct {
		name   string
		input  string
		source string
		want   []Package
	}{
		{
			name: "plain rows",
			// md.sh vmc::_get_current_ver assumes "name version" rows ($1/$2),
			// and vmc::install's vi template prints `# <$1>: <$2>` from the same.
			input:  "mdrive 1.2.3\nmdrive_conf 2.0.0-beta1\n",
			source: "md.sh vmc::_get_current_ver awk '{print $2}'",
			want:   []Package{mkPkg("mdrive", "1.2.3"), mkPkg("mdrive_conf", "2.0.0-beta1")},
		},
		{
			name:   "realistic long versions",
			input:  "mdrive test.4.0.1.mdrive4_zc_full_test_0811\nmdrive_dep 1.1.2\n",
			source: "mdrive4 vmc.sh MDRIVE_VERSION naming convention",
			want:   []Package{mkPkg("mdrive", "test.4.0.1.mdrive4_zc_full_test_0811"), mkPkg("mdrive_dep", "1.1.2")},
		},
		{
			name: "parenthesized version column",
			// tr -d '[:space:]()' hints the real list may print versions in parens.
			input:  "mdrive (1.0.0)\nmdrive_map\t(2.0.0)\n",
			source: "md.sh vmc::_get_current_ver `tr -d '()'`",
			want:   []Package{mkPkg("mdrive", "1.0.0"), mkPkg("mdrive_map", "2.0.0")},
		},
		{
			name:   "CRLF line endings",
			input:  "mdrive (1.2.3)\r\nmdrive_conf (1.0.0)\r\n",
			source: "CRLF tolerance (doc.go divergence)",
			want:   []Package{mkPkg("mdrive", "1.2.3"), mkPkg("mdrive_conf", "1.0.0")},
		},
		{
			name:  "blank comment and single-token decorations skipped",
			input: "========\n# comment row\n\nmdrive 1.0.0\n",
			want:  []Package{mkPkg("mdrive", "1.0.0")},
		},
		{
			name:  "empty output",
			input: "",
			want:  nil,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseList(tc.input)
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("ParseList() = %#v, want %#v (source: %s)", got, tc.want, tc.source)
			}
		})
	}
}

func TestParseSearch(t *testing.T) {
	cases := []struct {
		name   string
		input  string
		source string
		want   []Record
	}{
		{
			name: "canonical one-record-per-line",
			// Literal `name: %v, version: %v, platform: %v` in the vmc binary
			// (md_tool/vmc_deploy/vmc_linux_amd64_0.0.151).
			input: "name: mdrive, version: test.4.0.1.mdrive4_zc_full_test_0811, platform: orin\n" +
				"name: mdrive_conf, version: 1.0.0, platform: any\n",
			source: "vmc binary format string `name: %v, version: %v, platform: %v`",
			want: []Record{
				mkRec("mdrive", "test.4.0.1.mdrive4_zc_full_test_0811", "orin", ""),
				mkRec("mdrive_conf", "1.0.0", "any", ""),
			},
		},
		{
			name:   "compact colons no spaces",
			input:  "name:mdrive,version:1.2.3,platform:orin_dsv\n",
			source: "colon tolerance (doc.go divergence)",
			want:   []Record{mkRec("mdrive", "1.2.3", "orin_dsv", "")},
		},
		{
			name:   "quoted values",
			input:  "name: \"mdrive\", version: \"1.2.3\", platform: \"orin\"\n",
			source: "quote tolerance (doc.go divergence)",
			want:   []Record{mkRec("mdrive", "1.2.3", "orin", "")},
		},
		{
			name:   "uppercase keys tolerated",
			input:  "NAME: mdrive, VERSION: 1.2.3, PLATFORM: orin\n",
			source: "case-insensitive keys (doc.go divergence)",
			want:   []Record{mkRec("mdrive", "1.2.3", "orin", "")},
		},
		{
			name:   "equal sign separator",
			input:  "name = mdrive, version = 1.2.3, platform = orin\n",
			source: "colon/separator tolerance (doc.go divergence)",
			want:   []Record{mkRec("mdrive", "1.2.3", "orin", "")},
		},
		{
			name: "non-name leading lines ignored",
			// awk gate /^name:/: summary/noise lines never become records.
			input: "Total 3 packages found\nname: mdrive, version: 1.2.3, platform: orin\r\n" +
				"found: 3, name: mdrive_conf, version: 2.0.0\n",
			source: "md.sh vmc::finstall awk gate /^name:/",
			want:   []Record{mkRec("mdrive", "1.2.3", "orin", "")},
		},
		{
			name:   "name key without value",
			input:  "name:, version: 1.0.0, platform: orin\n",
			source: "awk keeps a /^name:/ line even with an empty name field",
			want:   []Record{mkRec("", "1.0.0", "orin", "")},
		},
		{
			name:   "version key without value",
			input:  "name: mdrive, version:, platform: orin\n",
			source: "awk field assignment with empty value",
			want:   []Record{mkRec("mdrive", "", "orin", "")},
		},
		{
			name:   "name only no version platform",
			input:  "name: mdrive\n",
			source: "vmc finstall awk record with only name field",
			want:   []Record{mkRec("mdrive", "", "", "")},
		},
		{
			name:  "empty output",
			input: "\n\n",
			want:  nil,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseSearch(tc.input)
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("ParseSearch() = %#v, want %#v (source: %s)", got, tc.want, tc.source)
			}
		})
	}
}

func TestParseSearchVerbose(t *testing.T) {
	cases := []struct {
		name   string
		input  string
		source string
		want   []Record
	}{
		{
			name: "canonical record block",
			// Index header + capitalized field lines: the shape the rollback awk
			// reconstructs rows from (`[Index:%v|ID:%v]` / `ReleaseTime: %v`).
			input: "[Index:0|ID:9f8a7b]\n" +
				"Name: mdrive\n" +
				"Version: test.4.0.1.mdrive4_zc_full_test_0811\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2024-03-01T10:30:00+08:00\n",
			source: "vmc binary `[Index:%v|ID:%v]` + rollback verbose awk",
			want: []Record{
				mkRec("mdrive", "test.4.0.1.mdrive4_zc_full_test_0811", "orin", "2024-03-01 10:30:00"),
			},
		},
		{
			name: "lowercase name line indented zulu time",
			input: "[Index:1|ID:abc]\n" +
				"\tname: mdrive_conf\n" +
				"\tVersion: 1.0.0\n" +
				"\tPlatform: orin_dsv\n" +
				"\tReleaseTime: 2024-01-02T03:04:05Z\n",
			source: "rollback awk accepts `[Nn]ame:` and truncates at 19 chars",
			want: []Record{
				mkRec("mdrive_conf", "1.0.0", "orin_dsv", "2024-01-02 03:04:05"),
			},
		},
		{
			name: "inline name on index line",
			input: "[Index:2|ID:xyz] name: mdrive_dep,\n" +
				"Version: 1.1.2\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2023-12-30T08:00:00.123+08:00\n",
			source: "rollback awk inline `name:` extraction on the Index line",
			want: []Record{
				mkRec("mdrive_dep", "1.1.2", "orin", "2023-12-30 08:00:00"),
			},
		},
		{
			name: "inline quoted name with brace noise",
			input: "[Index:3|ID:zzz] name: \"mdrive_map\",\n" +
				"Version: 3.1.0\n" +
				"Platform: orin_dsv\n" +
				"ReleaseTime: 2024-02-29T12:00:00Z\n",
			source: "quote/comma tolerance on inline name (doc.go divergence)",
			want: []Record{
				mkRec("mdrive_map", "3.1.0", "orin_dsv", "2024-02-29 12:00:00"),
			},
		},
		{
			name: "index line inline name plus labeled fields",
			input: "[Index:13|ID:inline] name: mdrive, Version: 1.2.3\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2024-06-01T12:00:00Z\n",
			source: "rollback awk unanchored /Version:/ also fires on the Index line",
			want: []Record{
				mkRec("mdrive", "1.2.3", "orin", "2024-06-01 12:00:00"),
			},
		},
		{
			name: "inline name wins over later name line",
			input: "[Index:4|ID:kk]\n" +
				"name: mdrive\n" +
				"Name: mdrive_conf\n" +
				"Version: 1.0.0\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2024-01-01T00:00:00Z\n",
			source: "rollback awk only fills name while it is empty",
			want: []Record{
				mkRec("mdrive", "1.0.0", "orin", "2024-01-01 00:00:00"),
			},
		},
		{
			name: "record without name still emitted record without version dropped",
			input: "[Index:5|ID:a]\n" +
				"Version: 0.9.0\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2023-01-01T00:00:00Z\n" +
				"[Index:6|ID:b]\n" +
				"name: orphan\n" +
				"[Index:7|ID:c]\n" +
				"name: mdrive\n" +
				"Version: 1.1.0\n" +
				"Platform: any\n",
			source: "rollback awk `if (version) print` flush rule",
			want: []Record{
				mkRec("", "0.9.0", "orin", "2023-01-01 00:00:00"),
				mkRec("mdrive", "1.1.0", "any", ""),
			},
		},
		{
			name: "json-ish quoted values with trailing commas",
			input: "[Index:8|ID:q] name: mdrive,\n" +
				"Version: \"1.2.3\",\n" +
				"Platform: orin,\n" +
				"ReleaseTime: \"2024-06-01T12:34:56Z\",\n",
			source: "quote/comma/brace tolerance (doc.go divergence)",
			want: []Record{
				mkRec("mdrive", "1.2.3", "orin", "2024-06-01 12:34:56"),
			},
		},
		{
			name: "quoted json keys",
			input: "[Index:9|ID:json]\n" +
				"\"Name\": \"mdrive\",\n" +
				"\"Version\": \"4.0.0\",\n" +
				"\"Platform\": \"orin_dsv\",\n" +
				"\"ReleaseTime\": \"2024-04-04T04:04:04Z\",\n",
			source: "quoted-key tolerance (doc.go divergence)",
			want: []Record{
				mkRec("mdrive", "4.0.0", "orin_dsv", "2024-04-04 04:04:04"),
			},
		},
		{
			name: "CRLF endings",
			input: "[Index:10|ID:crlf]\r\n" +
				"Name: mdrive\r\n" +
				"Version: 1.0.0\r\n" +
				"Platform: orin\r\n" +
				"ReleaseTime: 2024-05-05T05:05:05Z\r\n",
			source: "CRLF tolerance (doc.go divergence)",
			want: []Record{
				mkRec("mdrive", "1.0.0", "orin", "2024-05-05 05:05:05"),
			},
		},
		{
			name: "release time already spaced and longer than 19 runes",
			input: "[Index:11|ID:noT]\n" +
				"name: mdrive\n" +
				"Version: 2.0.0\n" +
				"Platform: orin\n" +
				"ReleaseTime: 2024-07-07 07:07:07.123456789\n",
			source: "rollback awk `sub(/T/, \" \"); substr(t,1,19)`",
			want: []Record{
				mkRec("mdrive", "2.0.0", "orin", "2024-07-07 07:07:07"),
			},
		},
		{
			name: "later duplicate field wins",
			input: "[Index:12|ID:two]\n" +
				"name: mdrive\n" +
				"Version: 1.0.0\n" +
				"Version: 1.5.0\n" +
				"Platform: orin\n",
			source: "rollback awk reassigns the field on every match",
			want: []Record{
				mkRec("mdrive", "1.5.0", "orin", ""),
			},
		},
		{
			name:  "no index blocks",
			input: "just some noise\n",
			want:  nil,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseSearchVerbose(tc.input)
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("ParseSearchVerbose() = %#v, want %#v (source: %s)", got, tc.want, tc.source)
			}
		})
	}
}

func TestParseEditText(t *testing.T) {
	cases := []struct {
		name   string
		text   string
		source string
		want   []Target
	}{
		{
			name: "mdrive does not steal mdrive_conf line",
			// md.sh _extract regex `^[[:space:]]*(mdrive)([^_a-zA-Z0-9]|$)`:
			// '_' is an identifier char, so `mdrive_conf:` never matches `mdrive`.
			text:   "mdrive_conf: 1.1.0\nmdrive: 2.0.0\n",
			source: "md.sh vmc::install _extract boundary guard",
			want: []Target{
				{Name: "mdrive", Version: "2.0.0"},
				{Name: "mdrive_conf", Version: "1.1.0"},
			},
		},
		{
			name:   "comment lines never match",
			text:   "# mdrive: 9.9.9\n#   mdrive_conf: 1.0.0\n",
			source: "grep anchors at line start; '#' breaks the match",
			want:   nil,
		},
		{
			name:   "keyword alternatives conf map dep model",
			text:   "conf: 3.0.0\nmap: 4.0.0\ndep: 5.0.0\nmodel: 6.0.0\n",
			source: "md.sh packages array `mdrive_conf|conf` style alternatives",
			want: []Target{
				{Name: "mdrive_conf", Version: "3.0.0"},
				{Name: "mdrive_map", Version: "4.0.0"},
				{Name: "mdrive_dep", Version: "5.0.0"},
				{Name: "mdrive_model", Version: "6.0.0"},
			},
		},
		{
			name:   "fullwidth colon separators",
			text:   "mdrive：1.2.3\n",
			source: "sed step `s/^[[:space:]:：]*//` fullwidth colon",
			want:   []Target{{Name: "mdrive", Version: "1.2.3"}},
		},
		{
			name:   "space before ascii colon",
			text:   "mdrive : 1.2.3\n",
			source: "extract step1 drops one non-identifier separator rune",
			want:   []Target{{Name: "mdrive", Version: "1.2.3"}},
		},
		{
			name:   "quoted and parenthesized value",
			text:   "mdrive: \"(1.2.3)\"\n",
			source: "sed steps 3+4 strip quotes and (（)）",
			want:   []Target{{Name: "mdrive", Version: "1.2.3"}},
		},
		{
			name:   "fullwidth parentheses value",
			text:   "mdrive: （1.0.2）\n",
			source: "sed steps 3+4 handle fullwidth parens",
			want:   []Target{{Name: "mdrive", Version: "1.0.2"}},
		},
		{
			name: "identifier suffix does not collide",
			// `mdrive2` and `mdrive_map` must not feed the `mdrive` spec.
			text:   "mdrive2: 1.0.0\nmdrive_map: 5.0.0\nmdrive: 2.0.0\n",
			source: "md.sh _extract `([^_a-zA-Z0-9]|$)` boundary",
			want: []Target{
				{Name: "mdrive", Version: "2.0.0"},
				{Name: "mdrive_map", Version: "5.0.0"},
			},
		},
		{
			name:   "leading whitespace and crlf",
			text:   "\t  mdrive: 1.2.3\r\n",
			source: "grep `^[[:space:]]*` + CRLF tolerance",
			want:   []Target{{Name: "mdrive", Version: "1.2.3"}},
		},
		{
			name: "first matching line wins even when empty",
			// Bash grep|head stops at the first hit; a bare `mdrive` line makes
			// the spec skip instead of falling through to the later real line.
			text:   "mdrive\nmdrive: 1.0.0\n",
			source: "vmc::install grep|head -n1 first-match semantics",
			want:   nil,
		},
		{
			name:   "no match yields no target",
			text:   "mdrive_model_version: 7.7.7\nmdrive_backup: 8.8.8\n",
			source: "identifier boundary prevents all default keywords",
			want:   nil,
		},
		{
			name: "realistic multi package paste",
			text: "以下为本次发布版本（复制到 vi 后保存）\n" +
				"mdrive: test.4.0.1.mdrive4_zc_full_test_0811\n" +
				"mdrive_conf: 1.0.2\n" +
				"mdrive_map: 3.1.0\n" +
				"mdrive_dep: 4.2.0\n" +
				"mdrive_model: 5.0.0\n",
			source: "md.sh packages array full default set",
			want: []Target{
				{Name: "mdrive", Version: "test.4.0.1.mdrive4_zc_full_test_0811"},
				{Name: "mdrive_conf", Version: "1.0.2"},
				{Name: "mdrive_map", Version: "3.1.0"},
				{Name: "mdrive_dep", Version: "4.2.0"},
				{Name: "mdrive_model", Version: "5.0.0"},
			},
		},
		{
			name:   "mdrive model line does not feed mdrive spec",
			text:   "mdrive_model: 5.0.0\nmdrive: 2.0.0\nmdrive_conf: 1.0.0\n",
			source: "identifier boundary between mdrive and mdrive_model",
			want: []Target{
				{Name: "mdrive", Version: "2.0.0"},
				{Name: "mdrive_conf", Version: "1.0.0"},
				{Name: "mdrive_model", Version: "5.0.0"},
			},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := ParseEditText(tc.text, DefaultVersionSpecs())
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("ParseEditText() = %#v, want %#v (source: %s)", got, tc.want, tc.source)
			}
		})
	}
}

func TestExtractEditVersion(t *testing.T) {
	cases := []struct {
		name     string
		text     string
		keywords []string
		want     string
	}{
		{
			name:     "single keyword hit",
			text:     "mdrive_conf: 9.9.9",
			keywords: []string{"mdrive_conf"},
			want:     "9.9.9",
		},
		{
			name:     "alternative keyword hit",
			text:     "conf: 1.0.0",
			keywords: []string{"mdrive_conf", "conf"},
			want:     "1.0.0",
		},
		{
			name:     "keyword must not match longer identifier",
			text:     "mdrive_conf: 9.9.9",
			keywords: []string{"mdrive"},
			want:     "",
		},
		{
			name:     "no match",
			text:     "nothing here",
			keywords: []string{"mdrive"},
			want:     "",
		},
		{
			name:     "empty keywords",
			text:     "mdrive: 1.0.0",
			keywords: nil,
			want:     "",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := ExtractEditVersion(tc.text, tc.keywords...); got != tc.want {
				t.Fatalf("ExtractEditVersion(%q, %v) = %q, want %q", tc.text, tc.keywords, got, tc.want)
			}
		})
	}
}

func TestDefaultVersionSpecs(t *testing.T) {
	want := []VersionSpec{
		{Name: "mdrive", Keywords: []string{"mdrive"}},
		{Name: "mdrive_conf", Keywords: []string{"mdrive_conf", "conf"}},
		{Name: "mdrive_map", Keywords: []string{"mdrive_map", "map"}},
		{Name: "mdrive_dep", Keywords: []string{"mdrive_dep", "dep"}},
		{Name: "mdrive_model", Keywords: []string{"mdrive_model", "model"}},
	}
	got := DefaultVersionSpecs()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("DefaultVersionSpecs() = %#v, want md.sh packages array %#v", got, want)
	}
}
