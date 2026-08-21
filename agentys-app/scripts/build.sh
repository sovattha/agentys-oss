#!/bin/bash
# Agentys - Local Build Script
# Usage: ./scripts/build.sh [platform]
# Platforms: mac, windows, linux, all

set -e

cd "$(dirname "$0")/.."

PLATFORM="${1:-all}"

echo "==================================="
echo "   Agentys Build Script"
echo "==================================="
echo ""

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    pnpm install
fi

# Build frontend
echo "Building frontend..."
pnpm build

# Build Tauri
echo ""
echo "Building Tauri app for: $PLATFORM"
echo ""

case "$PLATFORM" in
    mac|macos)
        echo "Building for macOS..."
        pnpm tauri build --target universal-apple-darwin
        echo ""
        echo "Build complete! Find your DMG in:"
        echo "  src-tauri/target/universal-apple-darwin/release/bundle/dmg/"
        ;;
    windows|win)
        echo "Building for Windows..."
        pnpm tauri build
        echo ""
        echo "Build complete! Find your installer in:"
        echo "  src-tauri/target/release/bundle/nsis/"
        echo "  src-tauri/target/release/bundle/msi/"
        ;;
    linux)
        echo "Building for Linux..."
        pnpm tauri build
        echo ""
        echo "Build complete! Find your packages in:"
        echo "  src-tauri/target/release/bundle/appimage/"
        echo "  src-tauri/target/release/bundle/deb/"
        ;;
    all)
        echo "Building for current platform..."
        pnpm tauri build
        echo ""
        echo "Build complete! Check src-tauri/target/release/bundle/"
        ;;
    *)
        echo "Unknown platform: $PLATFORM"
        echo "Usage: ./scripts/build.sh [mac|windows|linux|all]"
        exit 1
        ;;
esac

echo ""
echo "==================================="
echo "   Build Complete!"
echo "==================================="
