#!/usr/bin/env bash
# ============================================================
#  AGI Agent - Local Development Launcher (no Docker)
#  Works on macOS and Linux
#  Usage:
#    ./run-local.sh            # First-time setup + start
#    ./run-local.sh stop       # Stop all services
#    ./run-local.sh status     # Check what's running
#    ./run-local.sh restart    # Restart all services
#    ./run-local.sh logs       # Tail all logs
#    ./run-local.sh install    # Install deps only
# ============================================================

set -euo pipefail

ACTION="${1:-start}"
SKIP_INSTALL="${SKIP_INSTALL:-false}"
BACKEND_ONLY="${BACKEND_ONLY:-false}"
FRONTEND_ONLY="${FRONTEND_ONLY:-false}"

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
LOG_DIR="$SCRIPT_DIR/.local-logs"
PID_FILE="$SCRIPT_DIR/.local-pids"
BE_LOG="$LOG_DIR/backend.log"
FE_LOG="$LOG_DIR/frontend.log"

# ── Colors ────────────────────────────────────────────────────────────────────
if [ -t 1 ] && command -v tput &>/dev/null && tput setaf 1 &>/dev/null; then
  GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"
  CYAN="\033[96m"; DIM="\033[2m"; BOLD="\033[1m"
  PURPLE="\033[95m"; RESET="\033[0m"
else
  GREEN=""; YELLOW=""; RED=""; CYAN=""; DIM=""; BOLD=""; PURPLE=""; RESET=""
fi

ok()      { echo -e "  ${GREEN}✔${RESET} $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET} $*"; }
err()     { echo -e "  ${RED}✖${RESET} $*"; }
info()    { echo -e "  ${CYAN}›${RESET} $*"; }
dim()     { echo -e "  ${DIM}$*${RESET}"; }
section() { echo ""; echo -e "${BOLD}${PURPLE}  ▸ $*${RESET}"; echo -e "${DIM}  $(printf '─%.0s' {1..50})${RESET}"; }

banner() {
  echo ""
  echo -e "${PURPLE}${BOLD}  ╔════════════════════════════════════════════╗${RESET}"
  echo -e "${PURPLE}${BOLD}  ║${RESET}${BOLD}     AGI Agent · Local Dev Launcher         ${PURPLE}║${RESET}"
  echo -e "${PURPLE}${BOLD}  ║${RESET}${DIM}     No Docker · SQLite · In-Memory Redis    ${PURPLE}${BOLD}║${RESET}"
  echo -e "${PURPLE}${BOLD}  ╚════════════════════════════════════════════╝${RESET}"
  echo ""
}

# ── Prerequisites ─────────────────────────────────────────────────────────────
check_prerequisites() {
  section "Checking Prerequisites"
  local ok=true

  # Python
  if command -v python3 &>/dev/null; then
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PYMAJ=$(echo "$PYVER" | cut -d. -f1)
    PYMIN=$(echo "$PYVER" | cut -d. -f2)
    if [ "$PYMAJ" -lt 3 ] || { [ "$PYMAJ" -eq 3 ] && [ "$PYMIN" -lt 11 ]; }; then
      warn "Python $PYVER found — 3.11+ recommended"
    else
      ok "Python $PYVER"
    fi
  else
    err "Python 3 not found. Install from https://python.org (3.11+)"
    ok=false
  fi

  # Node
  if [ "$BACKEND_ONLY" != "true" ]; then
    if command -v node &>/dev/null; then
      NODEVER=$(node --version)
      NODEMAJ=$(echo "$NODEVER" | tr -d 'v' | cut -d. -f1)
      if [ "$NODEMAJ" -lt 18 ]; then
        warn "Node $NODEVER found — v18+ recommended"
      else
        ok "Node $NODEVER"
      fi
    else
      err "Node.js not found. Install from https://nodejs.org (v18+)"
      ok=false
    fi
  fi

  if [ "$ok" = "false" ]; then
    err "Prerequisites not met. Please install missing tools."
    exit 1
  fi
}

# ── Environment setup ─────────────────────────────────────────────────────────
setup_env() {
  section "Environment Setup"

  local env_file="$BACKEND_DIR/.env"
  local env_example="$SCRIPT_DIR/.env.local.example"

  if [ ! -f "$env_file" ]; then
    if [ -f "$env_example" ]; then
      cp "$env_example" "$env_file"
      ok "Created backend/.env from .env.local.example"
    else
      warn "No .env found — backend will use defaults"
      return
    fi
  else
    ok "backend/.env already exists"
  fi

  # Check for OpenRouter key
  if grep -q "OPENROUTER_API_KEY=sk-or-v1-your-key-here" "$env_file" || \
     ! grep -q "OPENROUTER_API_KEY=sk-or-" "$env_file"; then
    echo ""
    warn "OPENROUTER_API_KEY is not set in backend/.env"
    info "Get a free key at: ${CYAN}https://openrouter.ai/keys${RESET}"
    info "Free models available — no payment needed to start!"
    echo ""
    read -r -p "  Open backend/.env in editor now? [Y/n]: " EDIT
    if [ "${EDIT,,}" != "n" ]; then
      if command -v code &>/dev/null; then code "$env_file"
      elif command -v nano &>/dev/null; then nano "$env_file"
      elif command -v vim  &>/dev/null; then vim  "$env_file"
      fi
    fi
  fi
}

# ── Backend install ───────────────────────────────────────────────────────────
install_backend() {
  section "Backend Dependencies"

  if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    ok "Virtual environment created"
  else
    ok "Virtual environment exists"
  fi

  info "Installing Python packages..."
  "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q \
    --disable-pip-version-check 2>&1
  ok "Python packages installed"
}

# ── Frontend install ──────────────────────────────────────────────────────────
install_frontend() {
  section "Frontend Dependencies"

  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    info "Installing npm packages (first run, may take a minute)..."
    (cd "$FRONTEND_DIR" && npm install --silent 2>&1)
    ok "npm packages installed"
  else
    ok "node_modules already present"
  fi
}

# ── Wait for port ─────────────────────────────────────────────────────────────
wait_for_port() {
  local port=$1 name=$2 timeout=${3:-60}
  local elapsed=0
  local spinners=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  local i=0
  while [ "$elapsed" -lt "$timeout" ]; do
    if (echo > /dev/tcp/localhost/"$port") 2>/dev/null; then
      printf "\r  ${GREEN}✔${RESET} %-20s ready on :%-5s\n" "$name" "$port"
      return 0
    fi
    local spin="${spinners[$((i % ${#spinners[@]}))]}"
    printf "\r  ${YELLOW}%s${RESET} Waiting for %-16s (%d/%ds)" "$spin" "$name..." "$elapsed" "$timeout"
    sleep 2; elapsed=$((elapsed + 2)); i=$((i + 1))
  done
  printf "\r  ${RED}✖${RESET} %-20s did not start within %ds\n" "$name" "$timeout"
  return 1
}

# ── Start services ────────────────────────────────────────────────────────────
start_backend() {
  mkdir -p "$LOG_DIR"
  info "Starting FastAPI backend on http://localhost:8000 ..."
  (
    cd "$BACKEND_DIR"
    "$VENV_DIR/bin/uvicorn" app.main:app \
      --host 0.0.0.0 --port 8000 --reload \
      >> "$BE_LOG" 2>&1 &
    echo $! > "$PID_FILE.be"
  )
}

start_frontend() {
  mkdir -p "$LOG_DIR"
  info "Starting Next.js frontend on http://localhost:3000 ..."
  (
    cd "$FRONTEND_DIR"
    npm run dev >> "$FE_LOG" 2>&1 &
    echo $! > "$PID_FILE.fe"
  )
}

# ── Actions ───────────────────────────────────────────────────────────────────
do_start() {
  section "Starting Services"

  if [ "$FRONTEND_ONLY" != "true" ]; then
    start_backend
    wait_for_port 8000 "Backend API" 50 || warn "Backend slow — check $BE_LOG"
  fi

  if [ "$BACKEND_ONLY" != "true" ]; then
    start_frontend
    wait_for_port 3000 "Frontend UI" 90 || warn "Frontend slow — check $FE_LOG"
  fi
}

do_stop() {
  section "Stopping Services"

  if [ -f "$PID_FILE.be" ]; then
    local pid; pid=$(cat "$PID_FILE.be")
    kill "$pid" 2>/dev/null && ok "Backend stopped (PID $pid)" || warn "Backend PID $pid not found"
    rm -f "$PID_FILE.be"
  fi

  if [ -f "$PID_FILE.fe" ]; then
    local pid; pid=$(cat "$PID_FILE.fe")
    kill "$pid" 2>/dev/null && ok "Frontend stopped (PID $pid)" || warn "Frontend PID $pid not found"
    rm -f "$PID_FILE.fe"
  fi

  # Kill any orphaned uvicorn/next processes
  pkill -f "uvicorn app.main" 2>/dev/null || true
  pkill -f "next dev"         2>/dev/null || true
  ok "Services stopped"
}

do_status() {
  section "Service Status"
  for svc in "Backend API:8000" "Frontend UI:3000"; do
    local name="${svc%%:*}" port="${svc##*:}"
    if (echo > /dev/tcp/localhost/"$port") 2>/dev/null; then
      echo -e "  ${GREEN}●${RESET} ${BOLD}${name}${RESET}  ${CYAN}http://localhost:${port}${RESET}"
    else
      echo -e "  ${DIM}○${RESET} ${name}  ${DIM}http://localhost:${port}${RESET}  (stopped)"
    fi
  done
}

do_logs() {
  if [ -f "$BE_LOG" ] && [ -f "$FE_LOG" ]; then
    tail -f "$BE_LOG" "$FE_LOG"
  elif [ -f "$BE_LOG" ]; then
    tail -f "$BE_LOG"
  else
    warn "No logs found yet — start the services first"
  fi
}

show_completion() {
  echo ""
  echo -e "${GREEN}${BOLD}  ╔══════════════════════════════════════════════╗${RESET}"
  echo -e "${GREEN}${BOLD}  ║${RESET}${BOLD}    ✨  AGI Agent Running Locally           ${GREEN}║${RESET}"
  echo -e "${GREEN}${BOLD}  ╠══════════════════════════════════════════════╣${RESET}"
  echo -e "${GREEN}${BOLD}  ║${RESET}  ${DIM}Frontend:${RESET}  ${CYAN}http://localhost:3000${RESET}            ${GREEN}${BOLD}║${RESET}"
  echo -e "${GREEN}${BOLD}  ║${RESET}  ${DIM}Backend: ${RESET}  ${CYAN}http://localhost:8000${RESET}            ${GREEN}${BOLD}║${RESET}"
  echo -e "${GREEN}${BOLD}  ║${RESET}  ${DIM}API Docs:${RESET}  ${CYAN}http://localhost:8000/docs${RESET}       ${GREEN}${BOLD}║${RESET}"
  echo -e "${GREEN}${BOLD}  ║${RESET}  ${DIM}Storage: ${RESET}  SQLite + in-memory (no Docker!)         ${GREEN}${BOLD}║${RESET}"
  echo -e "${GREEN}${BOLD}  ╚══════════════════════════════════════════════╝${RESET}"
  echo ""
  dim "Logs:  .local-logs/backend.log   .local-logs/frontend.log"
  echo -e "  ${DIM}Stop:${RESET}  ${YELLOW}./run-local.sh stop${RESET}"
  echo ""

  # Try to open browser
  if command -v xdg-open &>/dev/null; then xdg-open "http://localhost:3000" &
  elif command -v open &>/dev/null;     then open    "http://localhost:3000" &
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  banner

  case "$ACTION" in
    stop)           do_stop;   exit 0 ;;
    status)         do_status; exit 0 ;;
    logs)           do_logs;   exit 0 ;;
    restart)        do_stop; sleep 2 ;;
    install)
      check_prerequisites
      setup_env
      install_backend
      install_frontend
      ok "All dependencies installed. Run: ./run-local.sh start"
      exit 0
      ;;
  esac

  check_prerequisites
  setup_env

  if [ "$SKIP_INSTALL" != "true" ]; then
    [ "$FRONTEND_ONLY" != "true" ] && install_backend
    [ "$BACKEND_ONLY"  != "true" ] && install_frontend
  fi

  do_start
  show_completion
}

main
