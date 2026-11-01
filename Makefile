# =============================================================================
# Horizon 极目楚天 · 常用命令
# -----------------------------------------------------------------------------
# 配方统一使用 `cd <dir> && <cmd>` 这一种与 shell 无关的写法，
# 因此在 Linux/macOS 的 sh 和 Windows 的 cmd.exe 下都能直接运行。
#
# Windows 使用说明：
#   1) 安装 GNU make（任选其一）
#        winget install ezwinports.make
#        choco install make
#   2) 在仓库根目录执行  make help
#   3) python 不在 PATH 默认位置时：  make dev-api PY=py
#   4) 本文件刻意不设置 SHELL，否则 Windows 下 make 会去找不存在的 /bin/sh
#
# 注意：help 的目标输出保持 ASCII，避免 Windows 代码页（GBK/936）下中文乱码；
#       中文文档见 README.md 与 docs/。
# =============================================================================

PY           ?= python
NPM          ?= npm
DOCKER       ?= docker
COMPOSE_FILE ?= infra/docker-compose.yml
ENV_FILE     ?= .env
COMPOSE      := $(DOCKER) compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)

.PHONY: help install install-api install-web dev-api dev-web up up-full down logs ps restart clean

help:
	@echo.
	@echo Horizon - available targets
	@echo ------------------------------------------------------------
	@echo   install      install backend venv deps + web node modules
	@echo   install-api  create api/.venv and pip install -r requirements.txt
	@echo   install-web  npm ci inside web/
	@echo   dev-api      run FastAPI on 127.0.0.1:8000 with --reload
	@echo   dev-web      run Next.js dev server on :3000
	@echo   up           docker compose up -d --build   (nginx on :80)
	@echo   up-full      same, plus celery worker (compose profile: full)
	@echo   down         docker compose down  (named volumes kept)
	@echo   logs         follow logs of every service
	@echo   ps           show service status
	@echo   restart      down, then up
	@echo   clean        drop python caches and web build output
	@echo ------------------------------------------------------------
	@echo overrides: PY=$(PY) NPM=$(NPM) DOCKER=$(DOCKER) ENV_FILE=$(ENV_FILE)
	@echo.

# ---------------------------------------------------------------- 本地开发 ----
install: install-api install-web

install-api:
	cd api && $(PY) -m venv .venv && $(PY) -m pip install --upgrade pip && $(PY) -m pip install -r requirements.txt

install-web:
	cd web && $(NPM) ci

dev-api:
	cd api && $(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-web:
	cd web && $(NPM) run dev

# ---------------------------------------------------------------- 容器编排 ----
up:
	$(COMPOSE) up -d --build

up-full:
	$(COMPOSE) --profile full up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

restart: down up

# -------------------------------------------------------------------- 清理 ----
clean:
	cd api && $(PY) -c "import shutil;[shutil.rmtree(p,ignore_errors=True) for p in ('.pytest_cache','.mypy_cache','.ruff_cache','__pycache__')]"
	cd web && $(PY) -c "import shutil;[shutil.rmtree(p,ignore_errors=True) for p in ('.next','out','.turbo')]"