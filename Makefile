# One-command local demo stack.
#
#   make up                  start every backend + web UI
#   make original            original Temporal workflow backend only
#   make langgraph           standalone LangGraph backend only
#   make temporal-langgraph  Temporal + LangGraph backend only
#   make down                stop everything this Makefile started
#   make status              what's running
#
# Logs live in /tmp/agent-*.log

ORIGINAL_API_PORT := 8000
LANGGRAPH_API_PORT := 8001
TEMPORAL_LANGGRAPH_API_PORT := 8002
WEB_PORT := 5173
TEMPORAL_UI_PORT := 8233

TEMPORAL_PID := /tmp/agent-temporal.pid
ORIGINAL_WORKER_PID := /tmp/agent-worker.pid
ORIGINAL_API_PID := /tmp/agent-api.pid
LANGGRAPH_API_PID := /tmp/agent-langgraph-api.pid
TEMPORAL_LANGGRAPH_WORKER_PID := /tmp/agent-temporal-langgraph-worker.pid
TEMPORAL_LANGGRAPH_API_PID := /tmp/agent-temporal-langgraph-api.pid
WEB_PID := /tmp/agent-web.pid

TEMPORAL_LOG := /tmp/agent-temporal.log
ORIGINAL_WORKER_LOG := /tmp/agent-worker.log
ORIGINAL_API_LOG := /tmp/agent-api.log
LANGGRAPH_API_LOG := /tmp/agent-langgraph-api.log
TEMPORAL_LANGGRAPH_WORKER_LOG := /tmp/agent-temporal-langgraph-worker.log
TEMPORAL_LANGGRAPH_API_LOG := /tmp/agent-temporal-langgraph-api.log
WEB_LOG := /tmp/agent-web.log

.PHONY: up original langgraph temporal-langgraph down status logs \
	postgres temporal worker api langgraph-api temporal-langgraph-worker \
	temporal-langgraph-api web kill-worker kill-temporal-langgraph-worker \
	kill-langgraph-api kill-workers kill-db db

up: postgres temporal worker api langgraph-api temporal-langgraph-worker temporal-langgraph-api web
	@echo ""
	@echo "  chat UI                    -> http://localhost:$(WEB_PORT)"
	@echo "  temporal UI                -> http://localhost:$(TEMPORAL_UI_PORT)"
	@echo "  original Temporal API      -> http://localhost:$(ORIGINAL_API_PORT)      (?backend=temporal)"
	@echo "  standalone LangGraph API   -> http://localhost:$(LANGGRAPH_API_PORT)      (?backend=langgraph)"
	@echo "  Temporal + LangGraph API   -> http://localhost:$(TEMPORAL_LANGGRAPH_API_PORT)      (?backend=temporal-langgraph)"

original: postgres temporal worker api web
	@echo "original Temporal backend ready: http://localhost:$(ORIGINAL_API_PORT)"

langgraph: postgres langgraph-api web
	@echo "standalone LangGraph backend ready: http://localhost:$(LANGGRAPH_API_PORT)"

temporal-langgraph: postgres temporal temporal-langgraph-worker temporal-langgraph-api web
	@echo "Temporal + LangGraph backend ready: http://localhost:$(TEMPORAL_LANGGRAPH_API_PORT)"

postgres:
	docker compose up -d

temporal:
	@if [ -s "$(TEMPORAL_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_PID)")" 2>/dev/null; then \
		echo "temporal dev server already running"; \
	else \
		(nohup temporal server start-dev --ui-port $(TEMPORAL_UI_PORT) > "$(TEMPORAL_LOG)" 2>&1 & echo $$! > "$(TEMPORAL_PID)"); \
		sleep 3; \
		echo "temporal dev server started (UI :$(TEMPORAL_UI_PORT))"; \
	fi

worker:
	@if [ -s "$(ORIGINAL_WORKER_PID)" ] && kill -0 "$$(cat "$(ORIGINAL_WORKER_PID)")" 2>/dev/null; then \
		echo "original Temporal worker already running"; \
	else \
		(nohup sh -c 'cd python && exec uv run worker.py' > "$(ORIGINAL_WORKER_LOG)" 2>&1 & echo $$! > "$(ORIGINAL_WORKER_PID)"); \
		echo "original Temporal worker started"; \
	fi

api:
	@if [ -s "$(ORIGINAL_API_PID)" ] && kill -0 "$$(cat "$(ORIGINAL_API_PID)")" 2>/dev/null; then \
		echo "original Temporal gateway already running (:$(ORIGINAL_API_PORT))"; \
	else \
		(nohup sh -c 'cd python && exec uv run uvicorn api:app --port $(ORIGINAL_API_PORT)' > "$(ORIGINAL_API_LOG)" 2>&1 & echo $$! > "$(ORIGINAL_API_PID)"); \
		echo "original Temporal gateway started (:$(ORIGINAL_API_PORT))"; \
	fi

langgraph-api:
	@if [ -s "$(LANGGRAPH_API_PID)" ] && kill -0 "$$(cat "$(LANGGRAPH_API_PID)")" 2>/dev/null; then \
		echo "standalone LangGraph gateway already running (:$(LANGGRAPH_API_PORT))"; \
	else \
		(nohup sh -c 'cd python-langchain && exec uv run uvicorn api:app --port $(LANGGRAPH_API_PORT)' > "$(LANGGRAPH_API_LOG)" 2>&1 & echo $$! > "$(LANGGRAPH_API_PID)"); \
		echo "standalone LangGraph gateway started (:$(LANGGRAPH_API_PORT))"; \
	fi

temporal-langgraph-worker:
	@if [ -s "$(TEMPORAL_LANGGRAPH_WORKER_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_LANGGRAPH_WORKER_PID)")" 2>/dev/null; then \
		echo "Temporal + LangGraph worker already running"; \
	else \
		(nohup sh -c 'cd python-langchain-temporal && exec uv run worker.py' > "$(TEMPORAL_LANGGRAPH_WORKER_LOG)" 2>&1 & echo $$! > "$(TEMPORAL_LANGGRAPH_WORKER_PID)"); \
		echo "Temporal + LangGraph worker started"; \
	fi

temporal-langgraph-api:
	@if [ -s "$(TEMPORAL_LANGGRAPH_API_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_LANGGRAPH_API_PID)")" 2>/dev/null; then \
		echo "Temporal + LangGraph gateway already running (:$(TEMPORAL_LANGGRAPH_API_PORT))"; \
	else \
		(nohup sh -c 'cd python-langchain-temporal && exec uv run uvicorn api:app --port $(TEMPORAL_LANGGRAPH_API_PORT)' > "$(TEMPORAL_LANGGRAPH_API_LOG)" 2>&1 & echo $$! > "$(TEMPORAL_LANGGRAPH_API_PID)"); \
		echo "Temporal + LangGraph gateway started (:$(TEMPORAL_LANGGRAPH_API_PORT))"; \
	fi

web:
	@if [ -s "$(WEB_PID)" ] && kill -0 "$$(cat "$(WEB_PID)")" 2>/dev/null; then \
		echo "web UI already running (:$(WEB_PORT))"; \
	else \
		(nohup sh -c 'cd web && exec python3 -m http.server $(WEB_PORT)' > "$(WEB_LOG)" 2>&1 & echo $$! > "$(WEB_PID)"); \
		echo "web UI started (:$(WEB_PORT))"; \
	fi

# The original Temporal crash-recovery demo beat.
kill-worker:
	-@[ -s "$(ORIGINAL_WORKER_PID)" ] && kill "$$(cat "$(ORIGINAL_WORKER_PID)")" 2>/dev/null || true
	@rm -f "$(ORIGINAL_WORKER_PID)"
	@echo "original Temporal worker killed - restart with: make worker"

kill-temporal-langgraph-worker:
	-@[ -s "$(TEMPORAL_LANGGRAPH_WORKER_PID)" ] && kill "$$(cat "$(TEMPORAL_LANGGRAPH_WORKER_PID)")" 2>/dev/null || true
	@rm -f "$(TEMPORAL_LANGGRAPH_WORKER_PID)"
	@echo "Temporal + LangGraph worker killed - restart with: make temporal-langgraph-worker"

kill-langgraph-api:
	-@[ -s "$(LANGGRAPH_API_PID)" ] && kill "$$(cat "$(LANGGRAPH_API_PID)")" 2>/dev/null || true
	@rm -f "$(LANGGRAPH_API_PID)"
	@echo "standalone LangGraph API killed - restart with: make langgraph-api"

kill-workers: kill-worker kill-temporal-langgraph-worker

# The retry beat: kill the DATABASE mid-conversation.
kill-db:
	docker kill chinook-postgres
	@echo "database killed - restore with: make db"

db:
	docker start chinook-postgres
	@echo "database back"

down:
	-@[ -s "$(ORIGINAL_WORKER_PID)" ] && kill "$$(cat "$(ORIGINAL_WORKER_PID)")" 2>/dev/null || true
	-@[ -s "$(ORIGINAL_API_PID)" ] && kill "$$(cat "$(ORIGINAL_API_PID)")" 2>/dev/null || true
	-@[ -s "$(LANGGRAPH_API_PID)" ] && kill "$$(cat "$(LANGGRAPH_API_PID)")" 2>/dev/null || true
	-@[ -s "$(TEMPORAL_LANGGRAPH_WORKER_PID)" ] && kill "$$(cat "$(TEMPORAL_LANGGRAPH_WORKER_PID)")" 2>/dev/null || true
	-@[ -s "$(TEMPORAL_LANGGRAPH_API_PID)" ] && kill "$$(cat "$(TEMPORAL_LANGGRAPH_API_PID)")" 2>/dev/null || true
	-@[ -s "$(WEB_PID)" ] && kill "$$(cat "$(WEB_PID)")" 2>/dev/null || true
	-@[ -s "$(TEMPORAL_PID)" ] && kill "$$(cat "$(TEMPORAL_PID)")" 2>/dev/null || true
	@rm -f "$(ORIGINAL_WORKER_PID)" "$(ORIGINAL_API_PID)" "$(LANGGRAPH_API_PID)" \
		"$(TEMPORAL_LANGGRAPH_WORKER_PID)" "$(TEMPORAL_LANGGRAPH_API_PID)" \
		"$(WEB_PID)" "$(TEMPORAL_PID)"
	docker compose down
	@echo "all stopped"

status:
	@printf "postgres                   : "; docker compose ps --format '{{.Status}}' postgres 2>/dev/null || echo "stopped"
	@printf "temporal                   : "; if [ -s "$(TEMPORAL_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_PID)")" 2>/dev/null; then echo "running (:7233, UI :$(TEMPORAL_UI_PORT))"; else echo "stopped"; fi
	@printf "original Temporal worker   : "; if [ -s "$(ORIGINAL_WORKER_PID)" ] && kill -0 "$$(cat "$(ORIGINAL_WORKER_PID)")" 2>/dev/null; then echo "running"; else echo "stopped"; fi
	@printf "original Temporal API      : "; if [ -s "$(ORIGINAL_API_PID)" ] && kill -0 "$$(cat "$(ORIGINAL_API_PID)")" 2>/dev/null; then echo "running (:$(ORIGINAL_API_PORT))"; else echo "stopped"; fi
	@printf "standalone LangGraph API   : "; if [ -s "$(LANGGRAPH_API_PID)" ] && kill -0 "$$(cat "$(LANGGRAPH_API_PID)")" 2>/dev/null; then echo "running (:$(LANGGRAPH_API_PORT))"; else echo "stopped"; fi
	@printf "Temporal + LangGraph worker: "; if [ -s "$(TEMPORAL_LANGGRAPH_WORKER_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_LANGGRAPH_WORKER_PID)")" 2>/dev/null; then echo "running"; else echo "stopped"; fi
	@printf "Temporal + LangGraph API   : "; if [ -s "$(TEMPORAL_LANGGRAPH_API_PID)" ] && kill -0 "$$(cat "$(TEMPORAL_LANGGRAPH_API_PID)")" 2>/dev/null; then echo "running (:$(TEMPORAL_LANGGRAPH_API_PORT))"; else echo "stopped"; fi
	@printf "web                        : "; if [ -s "$(WEB_PID)" ] && kill -0 "$$(cat "$(WEB_PID)")" 2>/dev/null; then echo "running (:$(WEB_PORT))"; else echo "stopped"; fi

logs:
	-@tail -n 20 "$(TEMPORAL_LOG)" "$(ORIGINAL_WORKER_LOG)" "$(ORIGINAL_API_LOG)" \
		"$(LANGGRAPH_API_LOG)" "$(TEMPORAL_LANGGRAPH_WORKER_LOG)" \
		"$(TEMPORAL_LANGGRAPH_API_LOG)" "$(WEB_LOG)" 2>/dev/null
