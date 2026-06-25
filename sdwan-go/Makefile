VERSION  ?= 1.0.0
BUILDDATE = $(shell date '+%Y-%m-%d %H:%M:%S')
LDFLAGS  := -s -w -X main.Version=$(VERSION) -X 'main.BuildDate=$(BUILDDATE)'
GOPROXY  ?= https://goproxy.cn,direct
DST       = dist

.PHONY: all linux macos windows tray clean test vet tidy

all: linux macos windows tray
	@ls -lh $(DST)/

linux:
	GOOS=linux   GOARCH=amd64 GOPROXY=$(GOPROXY) go build -ldflags "$(LDFLAGS)" -o $(DST)/sdwan-linux-amd64          .

macos:
	GOOS=darwin  GOARCH=amd64 GOPROXY=$(GOPROXY) go build -ldflags "$(LDFLAGS)" -o $(DST)/sdwan-macos-amd64           .
	GOOS=darwin  GOARCH=arm64 GOPROXY=$(GOPROXY) go build -ldflags "$(LDFLAGS)" -o $(DST)/sdwan-macos-arm64           .

windows:
	GOOS=windows GOARCH=amd64 GOPROXY=$(GOPROXY) go build -ldflags "$(LDFLAGS)" -o $(DST)/sdwan-windows-amd64.exe     .

tray:
	cd tray && GOOS=windows GOARCH=amd64 GOPROXY=$(GOPROXY) go build -ldflags="-s -w -H windowsgui" -o ../dist/sdwan-tray.exe .

clean:
	rm -f $(DST)/sdwan-*

test:
	go test -v -race -count=1 ./...

vet:
	go vet ./...

tidy:
	go mod tidy
