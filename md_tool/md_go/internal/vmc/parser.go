// Package vmc implements the pure parsing and selection logic that md.sh
// scatters across awk/sed/grep one-liners for the `vmc` package manager.
//
// This is the G1 scaffold stage: no CLI wiring, no SSH/TUI, no real `vmc`
// execution. Every function is a pure text parser or a pure selector, so the
// whole layer is testable against captured `vmc` output without a target
// device.
//
// md.sh reference (functions this package models):
//
//	vmc::_get_current_ver        -> ParseList + FindCurrentVersion
//	vmc::_get_latest_ver         -> ParseSearch + LatestVersion
//	vmc::finstall (pkg pick awk) -> ParseSearch + SelectPackageByVersion
//	vmc::rollback (verbose awk)  -> ParseSearchVerbose + MatchPackage
//	vmc::install (_extract)      -> ParseEditText + DefaultVersionSpecs
//
// See doc.go for the full mapping, the documented input formats and the list
// of deliberate divergences from the awk behaviour.
package vmc

import "strings"

// Package is one row of `vmc list` output: the installed package name and its
// version. Version is normalized the way vmc::_get_current_ver does
// (`awk '{print $2}' | tr -d '[:space:]()'`): parentheses and whitespace are
// removed.
type Package struct {
	Name    string
	Version string
}

// Record is one software entry returned by `vmc fsearch`. ReleaseTime is
// display-normalized the way the rollback awk normalizes it before joining a
// row: the first 'T' becomes a space and the value is cut to 19 runes, e.g.
// "2024-03-01T10:30:00+08:00" -> "2024-03-01 10:30:00".
type Record struct {
	Name        string
	Version     string
	Platform    string
	ReleaseTime string
}

// Target is one package to install, extracted from the text pasted into the
// `md install` vi editor. Name is the canonical package name; Version is the
// extracted value ("" when the paste contains no usable line for the spec).
type Target struct {
	Name    string
	Version string
}

// VersionSpec describes how a canonical package name is recognized inside a
// pasted version text. It mirrors one `name:pattern` entry of the `packages`
// array in md.sh; Keywords are the "|"-separated match alternatives.
type VersionSpec struct {
	Name     string
	Keywords []string
}

// DefaultVersionSpecs returns the specs that mirror the `packages` array
// declared at the top of md.sh. A fresh slice is returned on every call so
// callers can mutate it safely.
func DefaultVersionSpecs() []VersionSpec {
	return []VersionSpec{
		{Name: "mdrive", Keywords: []string{"mdrive"}},
		{Name: "mdrive_conf", Keywords: []string{"mdrive_conf", "conf"}},
		{Name: "mdrive_map", Keywords: []string{"mdrive_map", "map"}},
		{Name: "mdrive_dep", Keywords: []string{"mdrive_dep", "dep"}},
		{Name: "mdrive_model", Keywords: []string{"mdrive_model", "model"}},
	}
}

// ParseList maps `vmc list` output to packages. Each non-empty, non-comment
// line contributes one Package built from its first two whitespace-separated
// fields ($1 = name, $2 = version). The version column is normalized by
// removing whitespace and parentheses, replicating the `tr -d '[:space:]()'`
// step of vmc::_get_current_ver.
//
// Format source: md.sh vmc::_get_current_ver (grep "^<name> " + `awk '{print
// $2}'`) and the `vmc list` template line in vmc::install (`awk '{print "#   "
// $1 ": " $2}'`); the paren stripping hints the real version column may be
// parenthesized, so both `mdrive 1.2.3` and `mdrive (1.2.3)` must yield the
// same Version.
func ParseList(out string) []Package {
	var pkgs []Package
	for _, line := range splitLines(out) {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			// Tolerate header/decorative lines with a single token.
			continue
		}
		pkgs = append(pkgs, Package{
			Name:    fields[0],
			Version: compactListVersion(fields[1]),
		})
	}
	return pkgs
}

// ParseSearch maps the plain (non-verbose) `vmc fsearch` output to records.
// The canonical one-record-per-line shape is:
//
//	name: mdrive, version: 1.2.3, platform: orin
//
// Format source: the `name: %v, version: %v, platform: %v` literal found in
// the vmc release binary (vmc_deploy/vmc_linux_amd64_0.0.151) together with
// the awk in vmc::finstall that splits each line on ", " and inspects the
// `name:` / `version:` fields.
//
// Faithful awk semantics that are preserved:
//   - only lines whose first field key is `name` are treated as records
//     (the awk gate `/^name:/`); other lines such as summaries are ignored;
//   - a name key without a value still yields a record with an empty Name.
//
// Deliberate tolerances on top of the awk (the awk loses data in these cases,
// see doc.go): case-insensitive keys, optional spaces/quotes between key and
// ':'/'=', values wrapped in quotes, and CRLF endings.
func ParseSearch(out string) []Record {
	var recs []Record
	for _, line := range splitLines(out) {
		if rec, ok := parseSearchLine(line); ok {
			recs = append(recs, rec)
		}
	}
	return recs
}

// ParseSearchVerbose maps `vmc fsearch --verbose` output to records. The awk
// in vmc::rollback treats every `[Index:...|ID:...]` line as the start of a
// new record; the fields of the current record are then filled by
// Name/Version/Platform/ReleaseTime lines and the record is emitted as soon as
// the next Index line (or the end of input) arrives, but only when a version
// was seen.
//
// Format source: the `[Index:%v|ID:%v]` and `ReleaseTime: %v` literals found
// in the vmc release binary plus the field-state-machine awk in vmc::rollback
// (md.sh). The name may arrive from two independent places, matching the two
// sources the awk handles:
//   - inline on the Index line, e.g. `[Index:3|ID:abc] name: mdrive` (the awk
//     strips it at the first ',' or '}');
//   - from a dedicated `Name:` / `name:` line that follows the header.
//
// The inline name wins: a later Name line is ignored once a name is set (the
// awk only fills the name when it is still empty).
//
// After the inline name is extracted, the Index line still falls through to
// the same labeled checks as every other line: the awk patterns `/Platform:/`,
// `/Version:/` and `/ReleaseTime:/` are unanchored, so an Index line that
// carries such literals (e.g. a trailing `Version: 1.2.3`) fills those fields
// of the new record instead of being skipped by a `continue`.
func ParseSearchVerbose(out string) []Record {
	var recs []Record
	cur := Record{}
	for _, line := range splitLines(out) {
		if isIndexLine(line) {
			if cur.Version != "" {
				recs = append(recs, cur)
			}
			cur = Record{}
			if name, ok := indexInlineName(line); ok {
				cur.Name = name
			}
			// No `continue`: keep the labeled checks below, mirroring the
			// unanchored awk patterns that fire on the Index line too.
		}
		if cur.Name == "" {
			if name, ok := nameFieldValue(line); ok {
				cur.Name = name
			}
		}
		if v, ok := labeledValue(line, "Platform"); ok {
			cur.Platform = v
		}
		if v, ok := labeledValue(line, "Version"); ok {
			cur.Version = v
		}
		if v, ok := labeledValue(line, "ReleaseTime"); ok {
			cur.ReleaseTime = formatReleaseTime(v)
		}
	}
	if cur.Version != "" {
		recs = append(recs, cur)
	}
	return recs
}

// ParseEditText extracts install targets from the text that was pasted into
// the `md install` vi editor. It replicates vmc::install's _extract semantics
// for every spec: scan the text top-down, take the FIRST line whose start
// (after optional spaces/tabs) matches one of the spec keywords followed by a
// non-identifier boundary, then clean the value. The boundary check keeps
// `mdrive` from matching a `mdrive_conf:` line, exactly like the awk regex
// `^[[:space:]]*(pattern)([^_a-zA-Z0-9]|$)`.
//
// Specs whose first matching line yields an empty value are skipped, matching
// the Bash "未提取到版本号" skip. Targets keep the spec order.
func ParseEditText(text string, specs []VersionSpec) []Target {
	var targets []Target
	for _, spec := range specs {
		if version, ok := scanEditVersion(text, spec.Keywords); ok && version != "" {
			targets = append(targets, Target{Name: spec.Name, Version: version})
		}
	}
	return targets
}

// ExtractEditVersion is the single-spec convenience form of ParseEditText: it
// runs the _extract regex semantics for one keyword list and returns the first
// version found ("" when none).
func ExtractEditVersion(text string, keywords ...string) string {
	version, _ := scanEditVersion(text, keywords)
	return version
}
