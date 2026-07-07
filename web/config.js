// Named backend presets. The UI can switch between these from the start screen
// or with a query string, for example: http://localhost:5173?backend=temporal
window.AGENT_BACKENDS = {
  temporal: {
    label: 'Temporal workflow',
    url: 'http://localhost:8000',
    poweredBy: 'Powered by Temporal Workflow',
    conversationIdLabel: 'workflowId',
    conversationLinkBase: 'http://localhost:8233/namespaces/default/workflows',
  },
  'temporal-langgraph': {
    label: 'Temporal + LangGraph workflow',
    url: 'http://localhost:8002',
    poweredBy: 'Powered by Temporal + LangGraph',
    conversationIdLabel: 'workflowId',
    conversationLinkBase: 'http://localhost:8233/namespaces/default/workflows',
  },
  langgraph: {
    label: 'LangGraph standalone',
    url: 'http://localhost:8001',
    poweredBy: 'Powered by LangGraph',
    conversationIdLabel: 'conversationId',
    conversationLinkBase: '',
  },
};

window.DEFAULT_AGENT_BACKEND = 'langgraph';
