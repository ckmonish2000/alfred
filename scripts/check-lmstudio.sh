#!/usr/bin/env bash
# Check that LM Studio is serving and has the models Alfred needs.
# Uses the same settings as app/core/config.py: env vars, then .env, then defaults.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Load .env without overriding variables already set in the environment.
if [[ -f "$ROOT/.env" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key+x}" ]] && continue
    value="${value%\"}"; value="${value#\"}"
    export "$key=$value"
  done < "$ROOT/.env"
fi

BASE_URL="${LLM_BASE_URL:-http://localhost:1234/v1}"
LLM_MODEL="${LLM_MODEL:-qwen2.5-coder-7b-instruct-mlx}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-nomic-embed-text-v1.5}"
EMBEDDING_DIM="${EMBEDDING_DIM:-768}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
failed=0
fail() { red "✗ $*"; failed=1; }
ok() { green "✓ $*"; }

# 1. Server reachable
if ! models_json="$(curl -sf --max-time 5 "$BASE_URL/models")"; then
  red "✗ LM Studio is not reachable at $BASE_URL"
  echo "  Start it with: lms server start"
  exit 1
fi
ok "LM Studio is up at $BASE_URL"

# 2. Required models listed
available="$(printf '%s' "$models_json" | python3 -c 'import sys, json; print("\n".join(m["id"] for m in json.load(sys.stdin)["data"]))')"
for model in "$LLM_MODEL" "$EMBEDDING_MODEL"; do
  if grep -qxF "$model" <<<"$available"; then
    ok "Model available: $model"
  else
    fail "Model missing: $model"
    echo "  Load it with: lms load $model   (download first with: lms get $model)"
  fi
done

# 3. Embedding model actually works and has the dimension the DB expects
if grep -qxF "$EMBEDDING_MODEL" <<<"$available"; then
  dim="$(curl -sf --max-time 60 "$BASE_URL/embeddings" \
    -H 'Content-Type: application/json' \
    -d "{\"model\": \"$EMBEDDING_MODEL\", \"input\": [\"ping\"]}" |
    python3 -c 'import sys, json; print(len(json.load(sys.stdin)["data"][0]["embedding"]))' 2>/dev/null)"
  if [[ -z "$dim" ]]; then
    fail "Embedding request to $EMBEDDING_MODEL failed"
  elif [[ "$dim" != "$EMBEDDING_DIM" ]]; then
    fail "Embedding dimension is $dim, but the database column expects $EMBEDDING_DIM"
  else
    ok "Embeddings work ($dim dimensions)"
  fi
fi

if [[ $failed -ne 0 ]]; then
  red "Some checks failed."
  exit 1
fi
green "All checks passed."
