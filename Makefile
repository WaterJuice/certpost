DIST_DIR = dist

# Default target: print usage message
.PHONY: help
help:
	@echo "Usage:"
	@echo "  make build        - Build platform wheels and documentation"
	@echo "  make build-local  - Build for current platform only (fast, no wheels)"
	@echo "  make go-build     - Cross-compile Go binaries for all platforms"
	@echo "  make docs         - Build HTML documentation"
	@echo "  make clean        - Clean build artefacts"
	@echo "  make check        - Format check and lint Go source"
	@echo "  make format       - Format Go source with gofmt"
	@echo "  make dev          - Build for current platform + symlink into .venv"
	@echo "  make publish      - Publish output/ to PyPI and docs"

# Version string from git tags (falls back to commit hash if no tags)
VERSION_STR = $(shell git describe --tags --always 2>/dev/null | sed 's/-/.post.dev/' | sed 's/-g/-/')
GO_LDFLAGS = -s -w -X github.com/WaterJuice/certpost/internal/version.Version=$(VERSION_STR)

# Cross-compile Go binaries for all platforms
.PHONY: go-build
go-build:
	@command -v go >/dev/null 2>&1 || { echo "Error: Go is not installed. Install from https://go.dev/dl/"; exit 1; }
	@mkdir -p $(DIST_DIR)
	( CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-darwin-arm64      ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-darwin-arm64              ./cmd/certpost ) & \
	( CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-darwin-amd64      ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-darwin-amd64              ./cmd/certpost ) & \
	( CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-linux-amd64       ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-linux-amd64               ./cmd/certpost ) & \
	( CGO_ENABLED=0 GOOS=linux   GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-linux-arm64       ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=linux   GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-linux-arm64               ./cmd/certpost ) & \
	( CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-windows-amd64.exe ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-windows-amd64.exe         ./cmd/certpost ) & \
	( CGO_ENABLED=0 GOOS=windows GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-server-windows-arm64.exe ./cmd/certpost-server ) & \
	( CGO_ENABLED=0 GOOS=windows GOARCH=arm64 go build -ldflags='$(GO_LDFLAGS)' -o $(DIST_DIR)/certpost-windows-arm64.exe         ./cmd/certpost ) & \
	wait

# Build platform wheels + docs
.PHONY: build
build: check go-build docs
	rm -rf output/
	uv --version 2>/dev/null && true || pip3 install uv
	uv sync
	uv run bin2whl -c wheel.json --version-str $(VERSION_STR)
	cd html && python3 -m zipfile -c ../output/certpost-$(VERSION_STR)-docs.zip .
	@ln -sf $$(pwd)/dist/certpost-server-$$(go env GOOS)-$$(go env GOARCH) .venv/bin/certpost-server
	@ln -sf $$(pwd)/dist/certpost-$$(go env GOOS)-$$(go env GOARCH) .venv/bin/certpost
	@echo "certpost-server and certpost linked into .venv/bin/"

# Publish (requires output/ from make build)
.PHONY: publish
publish:
	uv run wj-publish output/

# Generate CLI help files for documentation
.PHONY: docs-help
docs-help: go-build
	@mkdir -p docs/mkdocs/_include
	COLUMNS=80 $(DIST_DIR)/certpost-server-$$(go env GOOS)-$$(go env GOARCH) --help > docs/mkdocs/_include/help_server.txt 2>&1 || true
	COLUMNS=80 $(DIST_DIR)/certpost-$$(go env GOOS)-$$(go env GOARCH) --help > docs/mkdocs/_include/help_main.txt 2>&1 || true

# Build the documentation
.PHONY: docs
docs: docs-help
	rm -rf html/
	uv --version 2>/dev/null && true || pip3 install uv
	uv sync
	VERSION=$(VERSION_STR) uv run wj-mkdocs -f docs/mkdocs.yml -d docs/mkdocs -o html/
	cp docs/docinfo.* html/
	rm -rf docs/mkdocs/_include html/_include

# Clean build artefacts
.PHONY: clean
clean:
	rm -rf html/ output/ dist/ .venv/

# Check format and lint Go source
.PHONY: check
check:
	@find cmd internal -name '*.go' | xargs gofmt -l | grep . && echo "Go files need formatting (run make format)" && exit 1 || true
	go vet ./...

# Format Go source
.PHONY: format
format:
	find cmd internal -name '*.go' | xargs gofmt -w

# Dev setup: build for current platform + symlink into venv
.PHONY: dev
dev: go-build
	uv --version 2>/dev/null && true || pip3 install uv
	uv sync
	@ln -sf $$(pwd)/dist/certpost-server-$$(go env GOOS)-$$(go env GOARCH) .venv/bin/certpost-server
	@ln -sf $$(pwd)/dist/certpost-$$(go env GOOS)-$$(go env GOARCH) .venv/bin/certpost
	@echo "certpost-server and certpost linked into .venv/bin/"

# Build for current platform only (fast, no wheels)
.PHONY: build-local
build-local: check
	mkdir -p output
	go build -ldflags='$(GO_LDFLAGS)' -o output/certpost-server ./cmd/certpost-server
	go build -ldflags='$(GO_LDFLAGS)' -o output/certpost ./cmd/certpost
	@echo "Built output/certpost-server and output/certpost ($(VERSION_STR))"
