BINARY := md
DIST := dist
PKG := ./cmd/md
GO ?= $(shell if [ -x /usr/local/go/bin/go ]; then printf /usr/local/go/bin/go; else command -v go; fi)
GOFMT ?= $(shell if [ -x /usr/local/go/bin/gofmt ]; then printf /usr/local/go/bin/gofmt; else command -v gofmt; fi)

.PHONY: fmt test build build-linux-amd64 build-linux-arm64 cross clean

fmt:
	$(GOFMT) -w $(shell find . -name '*.go' -not -path './vendor/*')

test:
	$(GO) test ./...

build:
	$(GO) build -o bin/$(BINARY) $(PKG)

build-linux-amd64:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w" -o $(DIST)/$(BINARY)_linux_amd64 $(PKG)

build-linux-arm64:
	mkdir -p $(DIST)
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags "-s -w" -o $(DIST)/$(BINARY)_linux_arm64 $(PKG)

cross: build-linux-amd64 build-linux-arm64

clean:
	rm -rf bin dist
