package vmc

import (
	"strings"
	"unicode/utf8"
)

// splitLines normalizes CRLF / bare CR into LF and splits the input into
// lines. CR stripping is applied up front for every parser so downstream
// logic never has to reason about \r; md.sh only tolerated \r at the final
// `tr -d` steps, this package makes the tolerance structural.
func splitLines(s string) []string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	s = strings.ReplaceAll(s, "\r", "\n")
	return strings.Split(s, "\n")
}

// compactListVersion removes whitespace and parentheses from a version token,
// replicating `tr -d '[:space:]()'` in vmc::_get_current_ver.
func compactListVersion(v string) string {
	var b strings.Builder
	for _, r := range v {
		if r == '(' || r == ')' || isASCIIWhitespace(r) {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

func isASCIIWhitespace(r rune) bool {
	return r == ' ' || (r >= '\t' && r <= '\r')
}

// parseSearchLine parses one plain `vmc fsearch` record line. The line is
// only accepted when the FIRST comma-separated segment carries the name key,
// replicating the awk gate `/^name:/` (vmc::finstall). Tolerant extensions:
// case-insensitive keys, optional spaces/quotes between key and ':'/'=' and
// quoted values.
func parseSearchLine(line string) (Record, bool) {
	line = strings.TrimSpace(line)
	if line == "" {
		return Record{}, false
	}
	segs := strings.Split(line, ",")
	firstKey, _, ok := parseSegment(segs[0])
	if !ok || !strings.EqualFold(firstKey, "name") {
		return Record{}, false
	}
	var rec Record
	for _, seg := range segs {
		key, value, ok := parseSegment(seg)
		if !ok {
			continue
		}
		switch strings.ToLower(key) {
		case "name":
			rec.Name = value
		case "version":
			rec.Version = value
		case "platform":
			rec.Platform = value
		}
	}
	return rec, true
}

// parseSegment splits one `key: value` / `key=value` comma segment. The key
// and value are trimmed of spaces and wrapping quotes.
func parseSegment(seg string) (key, value string, ok bool) {
	seg = strings.TrimSpace(seg)
	if seg == "" {
		return "", "", false
	}
	sep := strings.IndexAny(seg, ":=")
	if sep < 0 {
		return "", "", false
	}
	key = strings.Trim(strings.TrimSpace(seg[:sep]), `"'`)
	value = strings.Trim(strings.TrimSpace(seg[sep+1:]), `"'`)
	if key == "" {
		return "", "", false
	}
	return key, value, true
}

// isIndexLine reports whether the line starts a new verbose record block,
// matching the awk pattern `/^\[Index:/` in vmc::rollback. Leading whitespace
// is tolerated.
func isIndexLine(line string) bool {
	return strings.HasPrefix(strings.TrimLeft(line, " \t"), "[Index:")
}

// indexInlineName extracts a package name carried directly on the Index line,
// e.g. `[Index:3|ID:abc] name: mdrive`. It mirrors the awk
// `sub(/^.*[Nn]ame:[ ]*/, "", tmp); sub(/[,}].*$/, "", tmp)` sequence: the
// value after the LAST `name:` occurrence, cut at the first ',' or '}'.
func indexInlineName(line string) (string, bool) {
	idx := strings.LastIndex(strings.ToLower(line), "name:")
	if idx < 0 {
		return "", false
	}
	return cleanFieldValue(cutCommaBrace(line[idx+len("name:"):])), true
}

// nameFieldValue extracts the name from a dedicated `Name:`/`name:` field
// line. The awk anchored this at the start of the line
// (`/^[ \t]*[Nn]ame:/`); this version also tolerates a leading quote and
// spaces/quotes before the colon.
func nameFieldValue(line string) (string, bool) {
	i := 0
	for i < len(line) && strings.ContainsRune(" \t\"'", rune(line[i])) {
		i++
	}
	rest := line[i:]
	if !strings.HasPrefix(strings.ToLower(rest), "name") {
		return "", false
	}
	j := len("name")
	for j < len(rest) && strings.ContainsRune(" \t\"'", rune(rest[j])) {
		j++
	}
	if j >= len(rest) || rest[j] != ':' {
		return "", false
	}
	return cleanFieldValue(cutCommaBrace(rest[j+1:])), true
}

// labeledValue finds a `Label:`-style field anywhere in a verbose record
// line, mirroring the unanchored awk patterns `/Platform:/`, `/Version:/`
// and `/ReleaseTime:/`. It returns the remainder of the line after the colon.
// The awk kept the value that the awk field-splitting left over (including
// stray commas/quotes); this parser instead trims wrapping quotes and
// trailing commas/braces (see doc.go divergences).
func labeledValue(line, label string) (string, bool) {
	low := strings.ToLower(line)
	needle := strings.ToLower(label)
	for from := 0; ; {
		idx := strings.Index(low[from:], needle)
		if idx < 0 {
			return "", false
		}
		pos := from + idx
		j := pos + len(label)
		for j < len(line) && strings.ContainsRune(" \t\"'", rune(line[j])) {
			j++
		}
		if j < len(line) && line[j] == ':' {
			return cleanFieldValue(line[j+1:]), true
		}
		from = pos + 1
	}
}

// cleanFieldValue trims whitespace, strips wrapping quotes and drops
// trailing commas/braces from a verbose field value.
func cleanFieldValue(v string) string {
	for {
		next := v
		if len(next) >= 2 {
			if next[0] == '"' && next[len(next)-1] == '"' {
				next = next[1 : len(next)-1]
			} else if next[0] == '\'' && next[len(next)-1] == '\'' {
				next = next[1 : len(next)-1]
			}
		}
		next = strings.TrimSpace(strings.TrimRight(next, ",}"))
		if next == v {
			return v
		}
		v = next
	}
}

// cutCommaBrace truncates a raw name value at the first ',' or '}', matching
// the awk `sub(/[,}].*$/, "", tmp)` cleanup.
func cutCommaBrace(s string) string {
	for i := 0; i < len(s); i++ {
		if s[i] == ',' || s[i] == '}' {
			return s[:i]
		}
	}
	return s
}

// formatReleaseTime normalizes a raw ReleaseTime value for display: the first
// 'T' becomes a space and the result is cut to 19 runes, matching the awk
// `t=$0; sub(/T/, " ", t); time=substr(t, 1, 19)` in vmc::rollback.
func formatReleaseTime(t string) string {
	if i := strings.IndexByte(t, 'T'); i >= 0 {
		t = t[:i] + " " + t[i+1:]
	}
	runes := []rune(t)
	if len(runes) > 19 {
		runes = runes[:19]
	}
	return string(runes)
}

// scanEditVersion scans the pasted text top-down for the first line that
// matches one of the keywords (vmc::install _extract grep + head -n 1
// semantics). A matched line that yields an empty value still returns
// ok=true: the Bash pipeline stops at the first grep hit and would report
// "未提取到版本号" instead of scanning further.
func scanEditVersion(text string, keywords []string) (string, bool) {
	for _, line := range splitLines(text) {
		if value, ok := editLineVersion(line, keywords); ok {
			return value, true
		}
	}
	return "", false
}

// editLineVersion runs the _extract regex + sed chain for a single line and a
// single keyword. Line shape expected by the awk regex
// `^[[:space:]]*(pattern)([^_a-zA-Z0-9]|$)`:
//
//	optional leading spaces/tabs, then the keyword, then a rune that is NOT
//	[a-zA-Z0-9_] (or the end of line).
//
// The value cleaning replicates the four sed substitutions in order:
//
//	s/^[[:space:]]*(pattern)[^_a-zA-Z0-9]?//i
//	s/^[[:space:]:：]*//
//	s/^[[:space:]"（(]*//
//	s/[[:space:]"）)]*$//
//	s/\r//g
func editLineVersion(line string, keywords []string) (string, bool) {
	s := strings.TrimLeft(line, " \t")
	for _, kw := range keywords {
		if kw == "" {
			continue
		}
		if !strings.HasPrefix(strings.ToLower(s), strings.ToLower(kw)) {
			continue
		}
		rest := s[len(kw):]
		// Boundary: the next rune must not be an identifier char.
		if rest != "" {
			r, _ := utf8.DecodeRuneInString(rest)
			if isIdentRune(r) {
				continue
			}
		}
		// sed step 1: drop the keyword plus one optional separator rune.
		if rest != "" {
			_, sz := utf8.DecodeRuneInString(rest)
			rest = rest[sz:]
		}
		rest = trimLeadingSet(rest, func(r rune) bool {
			return isASCIIWhitespace(r) || r == ':' || r == '：'
		})
		rest = trimLeadingSet(rest, func(r rune) bool {
			return isASCIIWhitespace(r) || r == '"' || r == '（' || r == '('
		})
		rest = trimTrailingSet(rest, func(r rune) bool {
			return isASCIIWhitespace(r) || r == '"' || r == '）' || r == ')'
		})
		rest = strings.ReplaceAll(rest, "\r", "")
		return rest, true
	}
	return "", false
}

func isIdentRune(r rune) bool {
	return r == '_' ||
		(r >= 'a' && r <= 'z') ||
		(r >= 'A' && r <= 'Z') ||
		(r >= '0' && r <= '9')
}

func trimLeadingSet(s string, in func(rune) bool) string {
	cut := 0
	for _, r := range s {
		if !in(r) {
			break
		}
		cut += utf8.RuneLen(r)
	}
	return s[cut:]
}

func trimTrailingSet(s string, in func(rune) bool) string {
	end := len(s)
	for end > 0 {
		r, sz := utf8.DecodeLastRuneInString(s[:end])
		if !in(r) {
			break
		}
		end -= sz
	}
	return s[:end]
}
