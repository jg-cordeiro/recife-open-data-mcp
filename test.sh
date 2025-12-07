#!/usr/bin/env bash
# Test script for Recife Open Data MCP

set -e

echo "🚀 Starting test setup..."

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
echo "🎯 Starting interactive test client..."
echo "   You can ask questions in Portuguese like:"
echo "   - Quantas escolas existem?"
echo "   - Qual é a escola com mais alunos?"
echo "   - Liste todas as escolas de Santo Amaro"
echo ""

python client.py interactive
