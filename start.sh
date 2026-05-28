#!/usr/bin/env bash
set -e

echo "====================================="
echo "  AutoBid — AI Campaign Control Agent"
echo "====================================="

# Check for ANTHROPIC_API_KEY
if [ -z "$ANTHROPIC_API_KEY" ] && [ ! -f "backend/.env" ]; then
  echo ""
  echo "⚠  ANTHROPIC_API_KEY not set."
  echo "   Create backend/.env with: ANTHROPIC_API_KEY=your_key_here"
  echo "   The app will load but agent calls will fail without the key."
  echo ""
fi

# Start backend
echo "Starting backend on http://localhost:8000..."
cd backend
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# Wait for backend to be ready
echo "Waiting for backend..."
for i in {1..15}; do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "Backend ready."
    break
  fi
  sleep 1
done

# Start frontend
echo "Starting frontend on http://localhost:3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "AutoBid running:"
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
