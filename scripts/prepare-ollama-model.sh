#!/bin/sh
set -eu

BASE_MODEL=${PDA_BASE_MODEL:-qwen3.8:latest}
MODEL=${PDA_MODEL:-qwen3.8-pda:64k}
CONTEXT=${PDA_OLLAMA_CONTEXT:-65536}
TMP_FILE=$(mktemp "${TMPDIR:-/tmp}/pda-modelfile.XXXXXX")
trap 'rm -f "$TMP_FILE"' EXIT

cat > "$TMP_FILE" <<EOF
FROM $BASE_MODEL
PARAMETER num_ctx $CONTEXT
EOF

ollama create "$MODEL" -f "$TMP_FILE"
printf '%s\n' "Prepared Ollama model $MODEL with num_ctx=$CONTEXT"
