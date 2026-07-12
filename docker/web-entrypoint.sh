#!/bin/sh
set -eu

js_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

temporal_backend_url="$(js_escape "${TEMPORAL_BACKEND_URL:-}")"
langgraph_backend_url="$(js_escape "${LANGGRAPH_BACKEND_URL:-}")"
temporal_langgraph_backend_url="$(js_escape "${TEMPORAL_LANGGRAPH_BACKEND_URL:-/api}")"
temporal_ui_url="$(js_escape "${TEMPORAL_UI_URL:-}")"
default_backend="$(js_escape "${DEFAULT_AGENT_BACKEND:-temporal-langgraph}")"

first_backend=true
write_separator() {
  if [ "$first_backend" = true ]; then
    first_backend=false
  else
    printf ',\n'
  fi
}

write_temporal_backend() {
  if [ -n "$temporal_ui_url" ]; then
    conversation_link_base="${temporal_ui_url}/namespaces/default/workflows"
  else
    conversation_link_base=""
  fi
  write_separator
  cat <<EOF
  temporal: {
    label: 'Temporal workflow',
    url: "${temporal_backend_url}",
    poweredBy: 'Powered by Temporal Workflow',
    conversationIdLabel: 'workflowId',
    conversationLinkBase: "${conversation_link_base}",
  }
EOF
}

write_temporal_langgraph_backend() {
  if [ -n "$temporal_ui_url" ]; then
    conversation_link_base="${temporal_ui_url}/namespaces/default/workflows"
  else
    conversation_link_base=""
  fi
  write_separator
  cat <<EOF
  'temporal-langgraph': {
    label: 'Temporal + LangGraph workflow',
    url: "${temporal_langgraph_backend_url}",
    poweredBy: 'Powered by Temporal + LangGraph',
    conversationIdLabel: 'workflowId',
    conversationLinkBase: "${conversation_link_base}",
  }
EOF
}

write_langgraph_backend() {
  write_separator
  cat <<EOF
  langgraph: {
    label: 'LangGraph standalone',
    url: "${langgraph_backend_url}",
    poweredBy: 'Powered by LangGraph',
    conversationIdLabel: 'conversationId',
    conversationLinkBase: '',
  }
EOF
}

{
  printf '%s\n' 'window.AGENT_BACKENDS = {'
  [ -n "$temporal_backend_url" ] && write_temporal_backend
  [ -n "$temporal_langgraph_backend_url" ] && write_temporal_langgraph_backend
  [ -n "$langgraph_backend_url" ] && write_langgraph_backend
  printf '%s\n' '};'
  printf '\nwindow.DEFAULT_AGENT_BACKEND = "%s";\n' "$default_backend"
} > /usr/share/nginx/html/config.js
