package vmc

import "strings"

// DefaultPlatform is the platform keyword md.sh falls back to when a remote
// config row carries no platform column. It mirrors the `${platform:-orin}`
// default in vmc::_get_latest_ver.
const DefaultPlatform = "orin"

// SelectPackageByVersion picks the package name for a version query the same
// way the awk inside vmc::finstall does. Given the parsed plain `vmc fsearch`
// records (in output order) and the query version, the priority is:
//
//  1. the name of the first record whose version equals the query exactly;
//  2. otherwise the name of the first record whose version starts with the
//     query followed by "-" or ".";
//  3. otherwise the name of the first record seen (the awk calls it "last"
//     but only ever assigns the first line).
//
// It returns "" when no record matched the awk's `/^name:/` line gate at all
// (callers then report "未找到适用于...的包", like vmc::finstall).
func SelectPackageByVersion(records []Record, version string) string {
	var prefix, first string
	for _, rec := range records {
		if first == "" {
			first = rec.Name
		}
		if rec.Version == version {
			return rec.Name
		}
		if strings.HasPrefix(rec.Version, version+"-") ||
			strings.HasPrefix(rec.Version, version+".") {
			if prefix == "" {
				prefix = rec.Name
			}
		}
	}
	if prefix != "" {
		return prefix
	}
	return first
}

// MatchPackage keeps only the records whose Name exactly equals pkg. It
// mirrors the rollback exact-column filter
// (`awk -F ' \\| ' -v pkg=... '$4 == pkg'`) that is applied after the
// verbose records are rendered as `time | version | platform | name` rows.
// Records without a name never match a non-empty pkg.
func MatchPackage(records []Record, pkg string) []Record {
	var out []Record
	for _, rec := range records {
		if rec.Name == pkg {
			out = append(out, rec)
		}
	}
	return out
}

// FindCurrentVersion returns the installed version of pkg from parsed
// `vmc list` output, mirroring vmc::_get_current_ver
// (`grep "^<pkg> " | awk '{print $2}'`). When several rows share the name
// (Bash would have concatenated their versions because `tr -d` collapsed the
// newlines), the first row wins in Go.
func FindCurrentVersion(pkgs []Package, pkg string) (string, bool) {
	for _, p := range pkgs {
		if p.Name == pkg {
			return p.Version, true
		}
	}
	return "", false
}

// LatestVersion returns the latest remote version for pkg among the parsed
// plain `vmc fsearch` records, mirroring vmc::_get_latest_ver:
//
//	vmc fsearch ... | grep -iE "<platform>|any" | grep -F "name: <pkg>," | tail -n 1
//
// platform selects the keyword used for the platform filter; an empty value
// falls back to DefaultPlatform. "any" is always an accepted platform. The
// returned value is the Version of the LAST record that passes both filters
// ("tail -n 1" semantics; the server emits versions in ascending order, so
// last = newest). ok is false when no record survives the filters.
func LatestVersion(records []Record, pkg, platform string) (string, bool) {
	if platform == "" {
		platform = DefaultPlatform
	}
	var latest string
	found := false
	for _, rec := range records {
		if rec.Name != pkg {
			continue
		}
		if !platformMatch(rec, platform) {
			continue
		}
		latest = rec.Version
		found = true
	}
	return latest, found
}

// platformMatch reports whether a search record satisfies the platform
// filter. The Bash filter greps the whole rendered line
// (`name: x, version: y, platform: z`) for the platform keyword or "any"
// (case-insensitive); this implementation reconstructs that line from the
// parsed fields, so a keyword embedded in a name or version still matches —
// exactly like the grep over the raw line.
func platformMatch(rec Record, platform string) bool {
	line := strings.ToLower(rec.Name + ", " + rec.Version + ", " + rec.Platform)
	if strings.Contains(line, strings.ToLower(platform)) {
		return true
	}
	return strings.Contains(line, "any")
}
