#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/frontend" && pwd)"
STATIC_DIR="$(cd "${SCRIPT_DIR}/static" 2>/dev/null || true; pwd)"
if [ -z "${STATIC_DIR}" ]; then
  STATIC_DIR="${SCRIPT_DIR}/static"
fi

echo "========================================="
echo "Building apps/dsn_ui frontend..."
echo "Frontend Dir: ${FRONTEND_DIR}"
echo "Target Dir:   ${STATIC_DIR}"
echo "========================================="

cd "${FRONTEND_DIR}"
npm run build

echo "========================================="
echo "Frontend build and sync to static completed!"
echo "========================================="
