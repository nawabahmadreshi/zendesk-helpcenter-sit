#!/bin/bash
echo "🏁 Starting Aquera AI Help Demo..."

# Kill any existing server on port 8000
PIDS=$(lsof -t -i:8000)
if [ ! -z "$PIDS" ]; then
    echo "Stopping existing server on port 8000..."
    kill -9 $PIDS 2>/dev/null
fi

# Start the AI backend server
echo "Starting AI backend engine..."
export SKIP_VECTOR=true
export STORAGE_DIR="../storage"
source ../.venv/bin/activate && PYTHONPATH=.. python -m uvicorn app.ai_server:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

sleep 3

echo ""
echo "========================================================"
echo "✅ Demo is LIVE!"
echo "========================================================"
echo "To show the management team:"
echo "1. Open your browser (Chrome/Edge/Safari)"
echo "2. Go to: http://localhost:8000/widget/demo.html"
echo ""
echo "Close this terminal window or press Ctrl+C to stop."
echo "========================================================"
wait $SERVER_PID
