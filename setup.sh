#!/usr/bin/env bash
# setup.sh — One-command project setup
# Installs Python deps, sets up storage dirs, and optionally installs Ollama

set -e

VENV=".venv"
PYTHON="${VENV}/bin/python"
PIP="${VENV}/bin/pip"

echo "🚀 Aquera AI Help System — Setup"
echo "=================================="

# Python virtual environment
if [ ! -d "$VENV" ]; then
  echo "📦 Creating Python virtual environment..."
  python3 -m venv "$VENV"
fi

echo "📦 Installing Python dependencies..."
$PIP install --upgrade pip -q
$PIP install -r requirements.txt -q

# Storage directories
echo "📁 Creating storage directories..."
mkdir -p storage/{raw,processed/articles/{integration,general},metadata,vectordb,logs,models}

# .env file
if [ ! -f ".env" ]; then
  echo "📝 Creating .env from .env.example..."
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "  → Edit .env with your credentials before starting."
  else
    echo "  → .env.example not found; manually create .env."
  fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🤖 Local AI Options"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Option A — Embedded (llama-cpp-python, no external services):"
echo "  $PIP install llama-cpp-python huggingface-hub"
echo "  Then download the model via Admin → AI Provider → Download Local Model"
echo ""
echo "Option B — Ollama (local daemon):"

# Detect platform
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "  Mac detected. Install Ollama:"
  echo "  1. Download: https://ollama.ai/download"
  echo "  2. Or via Homebrew: brew install ollama"
  echo "  3. Then run: ollama pull phi3:mini"
  echo "  4. Set OLLAMA_BASE_URL=http://localhost:11434 in .env"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  echo "  Linux detected."
  echo "  Run: curl -fsSL https://ollama.ai/install.sh | sh"
  echo "  Then: ollama pull phi3:mini"
  echo "  Set OLLAMA_BASE_URL=http://localhost:11434 in .env"
fi

echo ""
echo "Option C — OpenRouter (cheapest cloud, free models available):"
echo "  1. Sign up at https://openrouter.ai"
echo "  2. Get your API key"
echo "  3. Set OPENROUTER_API_KEY=... in .env or Admin → AI Provider"
echo "  4. Default model: mistralai/mistral-7b-instruct:free (FREE)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup complete! Start the server with:"
echo "   source .venv/bin/activate"
echo "   uvicorn app.ai_server:app --host 0.0.0.0 --port 8000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
