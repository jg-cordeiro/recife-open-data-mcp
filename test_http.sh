#!/usr/bin/env bash
# Test script for Recife Open Data MCP (HTTP version)

set -e

echo "🚀 Starting HTTP MCP test setup..."

# Check if .env exists and has API key
if [ ! -f .env ]; then
    echo "❌ .env file not found. Creating from template..."
    cp .env.example .env
    echo "⚠️  Please fill in OPENROUTER_API_KEY in .env and re-run this script"
    exit 1
fi

if grep -q "replace-me\|sk-or-replace" .env; then
    echo "❌ OPENROUTER_API_KEY not configured in .env"
    exit 1
fi

# Activate venv
source .venv/bin/activate

echo "✅ Environment ready"
echo ""

# Check if MCP server is running
echo "🔍 Checking if MCP server is running on port 8000..."
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo ""
    echo "❌ MCP server is not running!"
    echo "   Please start it in another terminal with:"
    echo "   uvicorn server.http_server:app --reload --port 8000"
    echo ""
    echo "   Or use Docker Compose:"
    echo "   docker compose up -d"
    echo ""
    exit 1
fi

echo "✅ MCP server is running!"
echo ""
echo "🎯 Starting interactive HTTP test client..."
echo "   You can ask questions in Portuguese like:"
echo "   - Quantas escolas existem?"
echo "   - Qual é a escola com mais alunos?"
echo "   - Liste todas as escolas de Santo Amaro"
echo ""

python http_client.py interactive
