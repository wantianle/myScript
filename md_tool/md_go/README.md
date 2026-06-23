# md Go

`go-md` is the staged Go rewrite of `md_tool/md.sh`.

Current scope:

- Go CLI/TUI scaffold.
- `md` default TUI entry.
- `md tag ...` and `tag ...` command shells.
- Linux amd64 and Linux arm64 builds.

The current tag commands are placeholders. Business logic migration starts from tag store and record locator in the next phase.

## Build

```bash
make test
make build
make cross
```

Outputs:

```text
bin/md
dist/md_linux_amd64
dist/md_linux_arm64
```

## Run

```bash
./bin/md --version
./bin/md
./bin/md tag list
```

