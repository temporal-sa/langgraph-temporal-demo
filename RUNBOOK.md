# Runbook: LangGraph and Temporal support agent

This runbook is for presenting the demo. The [README](README.md) explains what it is and how it's built.

## What it shows

A music store's support agent searches the catalog, looks up a customer's orders, and buys tracks, with a person approving each purchase. The same agent runs three ways behind one chat UI: standalone LangGraph with a Postgres checkpointer, LangGraph on Temporal, and a hand-written Temporal Workflow. You run the same failure on two of them and the audience sees what each one does about it.

The demo makes three problems visible:

- **The model provider fails.** Random errors or a full outage hit the planning call. Standalone LangGraph retries three times inside the API process, then the turn fails. On Temporal, the planning Activity keeps retrying, and the turn finishes once the provider is back. Beat 3 shows it.
- **The process running the agent dies mid-turn.** Standalone LangGraph still has its checkpoint, but nothing runs the turn until someone calls resume. On Temporal, the Worker picks the turn up again from the Workflow's history by itself. Beat 4 shows it.
- **A purchase needs a person's approval, and must not charge twice.** All three pause for approval, and the LangGraph versions use LangGraph's own `interrupt()`. Each purchase carries an idempotency key, so a retried purchase returns the first invoice. Beat 2 shows it.

## Before you start

- Install Docker, the [Temporal CLI](https://docs.temporal.io/cli), and [uv](https://docs.astral.sh/uv/). The first `make up` installs the Python dependencies for all three implementations.
- Clone the repo and `cp .env.example .env`.
- To present the failure beats, use OpenAI. The **Random OpenAI failures** and **OpenAI Responses API** switches only inject failures when `LLM_PROVIDER=openai`; with Anthropic they do nothing. Set in `.env`:

  ```env
  LLM_PROVIDER=openai
  OPENAI_API_KEY=...
  OPENAI_MODEL=gpt-4o
  ```

  `.env.example` defaults to Anthropic (`LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`), which is fine for the approval beat. Every turn calls the model, so each run costs a little.
- The default customer, `sa@temporal.io`, is seeded with an account so orders and purchases work.

### On tmprl-demo.cloud

The catalog entry runs all three implementations against Temporal Cloud with OpenAI (`gpt-5.6-sol`), and the UI opens on **Temporal + LangGraph workflow**.

- The **workflowId** at the top of the chat isn't a link there, because the frontend gets no Temporal UI URL. Open the Namespace in Temporal Cloud and paste the workflow ID into the search.
- The Demo controls are shared. Each switch applies to that backend for everyone using the deployment, not just your conversation. Turn every switch back on when you finish.
- The frontend's Nginx proxy uses its default 60-second read timeout. A turn that waits longer than that (a long outage, a Worker left off) returns `504 Gateway Time-out` to the browser even though the Workflow carries on. Keep outages and Worker stops under a minute.
- There's no crashable environment for this demo; use the **Temporal worker** switch to stop the Worker.

### On your own Temporal Cloud Namespace

Set `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, and `TEMPORAL_API_KEY` in `.env`; every API and Worker reads it. The **workflowId** link in the local UI still points at `localhost:8233`, so open the Workflow in Temporal Cloud yourself.

## Start it

From the repository root:

```bash
make up
```

It starts Postgres (the seeded Chinook music store), a Temporal dev server, the original Temporal Worker and API (port 8000), the standalone LangGraph API (8001), the Temporal + LangGraph Worker and API (8002), and the web UI (5173). Then open:

- the chat at http://localhost:5173
- the Temporal UI at http://localhost:8233

A healthy start shows the **Customer Support Agent** start screen with **Customer email** set to `sa@temporal.io`, a **Backend** list, and **Start conversation**. `make status` lists every component as running, and `/tmp/agent-temporal-langgraph-worker.log` shows `demo controls enabled the temporal-langgraph worker poller`.

For the comparison beats, open two tabs, one per backend:

- http://localhost:5173/?backend=langgraph (**LangGraph standalone**)
- http://localhost:5173/?backend=temporal-langgraph (**Temporal + LangGraph workflow**)

In each tab, press **Start conversation**. The Temporal tab shows a **workflowId:** link to the Workflow in the Temporal UI; the standalone tab shows a plain **conversationId:**.

## The walkthrough

Model output varies, so the tracks and wording change from run to run. Press **Demo controls** (top right) to open the drawer, and `Esc` to close it. The drawer always applies to the backend in the current tab, shown under **Selected backend**.

### 1. The agent answers, and each step is an Activity

1. In the **Temporal + LangGraph workflow** tab, type `Find me some AC/DC tracks` and press `Enter`.
2. The agent replies with tracks, prices, and track IDs.
3. Click the **workflowId:** link. The history shows one Activity per graph step: `support-agent-temporal-langgraph.plan` for each model call and `support-agent-temporal-langgraph.tools` for each tool call.
4. Say: "This is an ordinary LangGraph graph, with a plan node and a tools node. The Temporal plugin runs each node as an Activity, so every model call and every database lookup is recorded, timed out, and retried by Temporal."

### 2. A purchase waits for approval

1. Type `Buy the first two of those`. The agent may confirm which tracks first; say yes.
2. An approval card appears: **⏸ Purchase approval required**, the purchase summary, and **Approve** and **Reject**.
3. Say: "The tools node called LangGraph's `interrupt()`. On Temporal, that pause is Workflow state, so it lasts as long as the approver needs, through Worker restarts."
4. Press **Approve**. The bubble reads **completing purchase…**, then the agent confirms the invoice.
5. In the Temporal UI, the history shows the `approve_purchase` Update, then a second `support-agent-temporal-langgraph.tools` Activity that made the purchase.
6. Say: "The purchase carries an idempotency key built from the conversation and the tool call. If that Activity were retried after the database committed, it would get the same invoice back, not a second charge."

### 3. The model provider goes down

1. In the **LangGraph standalone** tab, open **Demo controls** and turn off **OpenAI Responses API**. Send `What did I order last?`.
2. After three quick attempts, an error toast reads `Simulated OpenAI Responses API outage. Disable it in Demo controls to resume.` The turn is gone.
3. Turn the switch back on.
4. In the **Temporal + LangGraph workflow** tab, turn off **OpenAI Responses API** and send the same message. The typing bubble stays.
5. In the Temporal UI, the `plan` Activity is in **Pending Activities** with its attempt count rising and the outage as its last failure.
6. Turn the switch back on within about 30 seconds. The next retry succeeds and the reply arrives.
7. Say: "Same graph, same failure. Standalone LangGraph retried inside the API process and gave up. On Temporal, the retry belongs to the service, so the turn simply waited for the provider to come back."

The retry interval doubles each time, up to 100 seconds, so after a long outage the next attempt can be a while away. To show sporadic failures instead, turn on **Random OpenAI failures**, which fails about half of the planning calls: standalone LangGraph fails a turn when three attempts in a row fail, and Temporal retries until one succeeds.

### 4. The process dies mid-turn

1. In the **LangGraph standalone** tab, send `Show me some jazz tracks`, and while the typing bubble shows, turn off **LangGraph app** in Demo controls. This cancels the running graph and makes the API refuse requests, like a crashed process. The chat shows an error.
2. Turn **LangGraph app** back on. A card appears: **Checkpoint recovered; execution stopped**, with **Resume turn**.
3. Say: "The checkpoint survived in Postgres. But nobody is running the turn. Someone has to notice and call resume."
4. Press **Resume turn**. The turn finishes.
5. In the **Temporal + LangGraph workflow** tab, send the same message, and while the typing bubble shows, turn off **Temporal worker**. The Worker stops polling, and the turn waits. In the Temporal UI, the Workflow is still **Running**.
6. Turn **Temporal worker** back on. The turn finishes with no resume call.
7. Say: "Temporal keeps the turn's place in the Workflow's history, and any Worker on the Task Queue continues it. There's no resume endpoint because there's nothing to resume by hand."

Locally you can kill real processes instead: `make kill-langgraph-api` then `make langgraph-api` (open Demo controls afterwards to bring up the recovery card), and `make kill-temporal-langgraph-worker` then `make temporal-langgraph-worker`.

### 5. Optional: the same agent as a plain Workflow

Start a conversation on **Temporal workflow** (`?backend=temporal`). It behaves the same way, and its history shows `call_llm` and `execute_tool` Activities, each tool call labelled with the tool's name. Use it when someone asks what the agent looks like without a framework: [The same agent without LangGraph](#the-same-agent-without-langgraph).

### 6. End the conversation

In a Temporal tab, open Demo controls and press **End workflow**, then confirm. It cancels the Workflow and the page returns to the start screen.

## Show it in code

All links point at commit [`90f3c8e`](https://github.com/temporal-sa/langgraph-temporal-demo/commit/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0). Open a file locally with `code -g <path>:<line>`.

### Run each LangGraph node as a Temporal Activity

**When to use it:** after beat 1, or when someone asks how much of their LangGraph code changes.

**Where it is:** [`python-langgraph-temporal/graph/agent.py` lines 97–122](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/graph/agent.py#L97-L122) (`code -g python-langgraph-temporal/graph/agent.py:97`), registered in [`python-langgraph-temporal/worker.py` lines 20–27](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/worker.py#L20-L27)

```python
def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(
        "plan",
        plan,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(seconds=60),
        },
    )
    builder.add_node(
        "tools",
        execute_tools,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(seconds=30),
        },
    )
    builder.add_edge(START, "plan")
    # ...
    return builder
```

```python
def worker_factory() -> Worker:
    plugin = LangGraphPlugin(graphs={GRAPH_NAME: build_graph()})
    return Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[SupportAgentWorkflow],
        plugins=[plugin],
    )
```

**What you need to understand:**

- The graph is standard LangGraph: two nodes and conditional edges. The only Temporal-specific part is each node's `metadata`. `execute_in: "activity"` makes the node an Activity named `<graph>.<node>`, and the other keys are passed to `workflow.execute_activity`.
- The plugin requires `execute_in` on every node, and rejects a node that sets a LangGraph `retry_policy`; retries belong to Temporal.
- No `retry_policy` is set here, so Temporal's default applies: retry from 1 second, doubling, up to 100 seconds apart, with no attempt limit. A customer would usually set one in the same `metadata`.
- The tools node runs one tool call per invocation, so each tool call is its own Activity and a retry repeats one call, not a batch.
- The plugin is experimental. The repo pins `temporalio` 1.30.0.

**Docs:** [LangGraph integration (Python)](https://docs.temporal.io/develop/python/integrations/langgraph), [Retry Policies](https://docs.temporal.io/encyclopedia/retry-policies)

### Let Temporal own the retries

**When to use it:** during beat 3, or when someone asks why the standalone app gave up and Temporal didn't.

**Where it is:** [`python-langgraph-temporal/activities/llm.py` lines 30–54](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/activities/llm.py#L30-L54) and [lines 81–98](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/activities/llm.py#L81-L98) (`code -g python-langgraph-temporal/activities/llm.py:30`)

```python
async def call_llm(req: LLMRequest) -> LLMResponse:
    try:
        await _maybe_fail_openai_call()
        model = _chat_model().bind_tools(_langchain_tools())
        response = await model.ainvoke(
            # ...
        )
    except (
        anthropic.BadRequestError,
        anthropic.AuthenticationError,
        # ...
        openai.NotFoundError,
    ) as e:
        raise ApplicationError(
            f"LLM request rejected: {e}", type="LLMRequestRejected", non_retryable=True
        ) from e
```

```python
def _chat_model():
    if config.LLM_PROVIDER == "openai":
        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            use_responses_api=True,
            max_retries=0,
            timeout=30,
        )
```

**What you need to understand:**

- `max_retries=0` turns off the client library's own retries, so every retry is a Temporal Activity attempt you can see in the UI.
- A rejected request, such as a bad key or a malformed call, is non-retryable and fails at once. Outages, rate limits, and the demo's injected failures are ordinary errors, so Temporal retries them.
- The 30-second client timeout sits inside the node's 60-second Start-To-Close Timeout, so a hung call fails and retries before Temporal times the attempt out.

### Pause for approval with LangGraph's own interrupt

**When to use it:** during beat 2.

**Where it is:** [`python-langgraph-temporal/graph/agent.py` lines 46–64](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/graph/agent.py#L46-L64) (`code -g python-langgraph-temporal/graph/agent.py:46`) and [`python-langgraph-temporal/workflows/agent.py` lines 89–103](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/workflows/agent.py#L89-L103)

```python
if call.name == "purchase_tracks":
    pending = PendingPurchase(
        approval_id=f"{call.id}:{len(messages)}",
        track_ids=call.args.get("track_ids", []),
        description=call.args.get("summary"),
    )
    resume_value = interrupt(pending.model_dump(mode="json"))
    decision = ApprovalDecision.model_validate(resume_value)
    if decision.approved:
        result = execute_tool(
            ToolRequest(
                call=call,
                customer_email=state["customer_email"],
                idempotency_key=f"{state['conversation_id']}:{call.id}",
            )
        )
    else:
        reason = f" Reason: {decision.reason}" if decision.reason else ""
        result = f"The customer's approver DECLINED this purchase.{reason}"
```

```python
@workflow.update
def approve_purchase(
    self, approval_id: str, decision: ApprovalDecision
) -> None:
    # ...
    self.graph_input = Command(resume=decision.model_dump(mode="json"))
    self.pending_purchase = None
    self.turn_in_progress = True
```

**What you need to understand:**

- The node is the same in both LangGraph versions: call `interrupt()` with the pending purchase, and resume with `Command(resume=...)`. Nothing in the graph knows about Temporal.
- On Temporal, the first `tools` Activity returns the interrupt, the Workflow stores the pending purchase and waits, and the `approve_purchase` Update hands the decision back. A second `tools` Activity runs the node again with the decision and makes the purchase.
- The Workflow compiles the graph with LangGraph's `InMemorySaver`. That's safe because replaying the Workflow's history rebuilds it; there's no Postgres checkpointer on this side.
- The approval is an Update, so the browser learns at once whether the decision was accepted. The wait has no timeout here; a customer would usually add one and decline when it fires.
- If `approve_purchase` raises (a stale or repeated approval), the error is a plain `RuntimeError`, which fails the Workflow Task instead of rejecting the Update. See the troubleshooting table.

**Docs:** [LangGraph integration (Python)](https://docs.temporal.io/develop/python/integrations/langgraph), [Python: Updates](https://docs.temporal.io/develop/python/workflows/message-passing#updates)

### One Workflow per conversation, one Update per message

**When to use it:** after beat 4, or when someone asks where the conversation lives.

**Where it is:** [`python-langgraph-temporal/workflows/agent.py` lines 43–87](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/workflows/agent.py#L43-L87) (`code -g python-langgraph-temporal/workflows/agent.py:43`)

```python
app = graph(GRAPH_NAME).compile(checkpointer=InMemorySaver())
config = RunnableConfig(
    {"configurable": {"thread_id": workflow.info().workflow_id}}
)
while True:
    await workflow.wait_condition(lambda: self.turn_in_progress)
    graph_input = self.graph_input
    # ...
    result: GraphOutput = await app.ainvoke(
        graph_input,
        config,
        version="v2",
    )
    self.state = _agent_state(result.value)
    self.pending_purchase = _pending_from_interrupts(result.interrupts)
    self.graph_input = None
    self.turn_in_progress = False

@workflow.update
async def send_message(self, text: str) -> TurnResult:
    # ...
    self.turn_in_progress = True
    await workflow.wait_condition(lambda: not self.turn_in_progress)

    reply = self._last_assistant_text(since=turn_start)
    if self.pending_purchase is not None:
        return TurnResult(status="awaiting_approval", reply=reply)
    return TurnResult(status="reply", reply=reply)
```

**What you need to understand:**

- The Workflow ID is the conversation ID and the LangGraph thread ID. The Workflow runs a loop that waits for a turn, runs the graph once, and waits again.
- Each chat message is an Update. The API's HTTP call waits for the Update's result, so the reply comes back on the same request.
- This is why beat 4 needs no resume call: the turn's progress is in the Workflow's history, and whichever Worker polls the Task Queue next replays to the same point and schedules the next Activity.
- Limits: the Workflow never continues-as-new, so its history grows with every turn. A long-lived production chat would need Continue-As-New, carrying the state across.

**Docs:** [Python: Continue-As-New](https://docs.temporal.io/develop/python/workflows/continue-as-new)

### Make the purchase safe to retry

**When to use it:** after beat 2, or when someone asks what happens if the purchase is retried after it went through.

**Where it is:** [`support-agent-common/src/support_agent_common/database.py` lines 109–140](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/support-agent-common/src/support_agent_common/database.py#L109-L140) (`code -g support-agent-common/src/support_agent_common/database.py:109`)

```python
    """Create one invoice per durable tool execution.

    The idempotency row is inserted in the same transaction as the invoice. A
    concurrent retry blocks on the unique key, then reads the committed invoice
    instead of inserting a second purchase.
    """
    # ...
    with _connect(db_url) as conn:
        # ...
        claimed = conn.execute(
            """INSERT INTO purchase_idempotency (idempotency_key)
               VALUES (%s)
               ON CONFLICT (idempotency_key) DO NOTHING
               RETURNING idempotency_key""",
            (idempotency_key,),
        ).fetchone()
        if claimed is None:
            existing = conn.execute(
                """SELECT invoice_id FROM purchase_idempotency
                   WHERE idempotency_key = %s""",
                (idempotency_key,),
            ).fetchone()
            # ...
            return _purchase_result(conn, existing["invoice_id"])
```

**What you need to understand:**

- The key is `<conversation ID>:<tool call ID>`, set in the graph node above. Both parts are stable across retries.
- An Activity can run more than once: a retry after the database committed but before the result reached Temporal runs the purchase again. Retries alone don't make a side effect safe; the key does. The README's comparison table says the same for both runtimes.
- In a real system the key would go to the payment provider, which most accept for exactly this reason.

### What standalone LangGraph does instead

**When to use it:** during beats 3 and 4, to show the code behind the standalone side.

**Where it is:** [`python-langgraph/graph/agent.py` lines 77–84](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph/graph/agent.py#L77-L84) and [lines 270–282](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph/graph/agent.py#L270-L282) (`code -g python-langgraph/graph/agent.py:77`)

```python
NODE_RETRY_POLICY = RetryPolicy(
    initial_interval=1,
    backoff_factor=2,
    max_interval=8,
    max_attempts=3,
    jitter=True,
    retry_on=_retryable,
)
```

```python
async def resume(self, conversation_id: str) -> TurnResult:
    if conversation_id in self._active_runs:
        raise TurnInProgressError("a turn is already running")
    async with self._lock(conversation_id):
        snapshot = await self._snapshot(conversation_id)
        status = self._status(conversation_id, snapshot)
        if status["status"] != "interrupted":
            raise TurnNotResumableError("the conversation has no interrupted turn")

        state = _agent_state(snapshot.values)
        turn_start = _last_user_index(state["messages"])
        result = await self._invoke(conversation_id, None)
        return _turn_result(result, since=turn_start)
```

**What you need to understand:**

- This is a fair comparison, not a straw man. The standalone app uses LangGraph's own retry policy, node timeouts, and a production Postgres checkpointer (`AsyncPostgresSaver`), so conversations and pending approvals survive a restart.
- The retries run inside the API process. Three attempts at most, and if the process dies, the retries die with it. You could raise `max_attempts`, but a request handler can only wait so long.
- After a crash, the checkpoint shows a turn still `running` with no task behind it, and the API reports it as `interrupted`. Running it again takes an explicit `POST /conversations/{id}/resume`. Something in production would have to find those threads and call it.
- This compares self-hosted open-source LangGraph, not LangGraph Platform.

### The same agent without LangGraph

**When to use it:** beat 5, or when someone asks what the agent looks like as plain Temporal code.

**Where it is:** [`python/workflows/agent.py` lines 41–91](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python/workflows/agent.py#L41-L91) (`code -g python/workflows/agent.py:41`)

```python
while True:
    await workflow.wait_condition(lambda: self.turn_in_progress)

    while True:  # the ReAct loop for this turn
        plan_response = await workflow.execute_activity(
            call_llm,
            LLMRequest(messages=self.messages),
            start_to_close_timeout=timedelta(seconds=60),
        )
        self.messages.append(plan_response.message)

        if not plan_response.message.tool_calls:
            break

        for call in plan_response.message.tool_calls:
            if call.name == "purchase_tracks":
                # ...
                await workflow.wait_condition(lambda: self.approval is not None)
                # ...
            else:
                result = await workflow.execute_activity(
                    execute_tool,
                    ToolRequest(call=call, customer_email=customer_email),
                    start_to_close_timeout=timedelta(seconds=30),
                    summary=call.name,
                )
```

**What you need to understand:**

- The agent loop is a `while` loop: plan, run each tool call, repeat until the model stops asking for tools. The approval is a `wait_condition` on Workflow state that the `approve_purchase` Update sets.
- It behaves the same as the LangGraph version under failure, because the durability comes from the Workflow and its Activities in both cases.
- A customer already on LangGraph keeps the graph and adds the plugin. A customer starting fresh can write the loop directly. Either way the retries, timeouts, and recovery are Temporal's.

### What's demo-only

When someone asks what they'd change for their own system, these are the parts to leave out:

- **The provider failures.** [`support-agent-common/src/support_agent_common/demo_controls.py` lines 149–170](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/support-agent-common/src/support_agent_common/demo_controls.py#L149-L170): before each OpenAI call, the code reads the switches from a `demo_control` table in Postgres and raises a simulated outage or random failure.
- **The Worker switch.** [`support-agent-common/src/support_agent_common/demo_controls.py` lines 173–218](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/support-agent-common/src/support_agent_common/demo_controls.py#L173-L218): each Worker process checks the table every second and starts or shuts down its Temporal Worker. A real deployment just runs the Worker.
- **The LangGraph app switch.** [`python-langgraph/graph/agent.py` lines 300–309](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph/graph/agent.py#L300-L309): `simulate_crash` cancels the in-process graph runs, standing in for a crashed API process.
- **End workflow.** [`python-langgraph-temporal/api.py` lines 278–287](https://github.com/temporal-sa/langgraph-temporal-demo/blob/90f3c8e00dd36d2a3092988abd56ba3457d6f0b0/python-langgraph-temporal/api.py#L278-L287): a cancel request so presenters can clean up. A real chat would end its Workflow from the Workflow itself, for example after a period of inactivity.

## Reset and tear down

- **Between runs:** reload each tab to get the start screen, and press **Start conversation** for a new conversation. On the Temporal backends, press **End workflow** first so the old Workflow doesn't stay open.
- **Before you leave:** open Demo controls in each tab and turn every switch back to its normal state (**Random OpenAI failures** off; **OpenAI Responses API**, **LangGraph app**, and **Temporal worker** on). The switch state lives in Postgres, so it survives restarts.
- **To stop everything locally:** `make down`. It stops every process and the dev server, which keeps nothing on disk, and removes the Postgres container but keeps its volume, so purchases, LangGraph checkpoints, and switch states remain.
- **To reset the database to the seed data:** `make down`, then `docker compose down -v`, then `make up`.

## When something goes wrong

| What you see | Likely cause | Fix |
|---|---|---|
| Turning on **Random OpenAI failures** or off **OpenAI Responses API** changes nothing | `LLM_PROVIDER` isn't `openai` | Set `LLM_PROVIDER=openai` and `OPENAI_API_KEY` in `.env`, then `make down` and `make up` |
| A Temporal turn never finishes | **OpenAI Responses API** or **Temporal worker** is off for that backend | Open Demo controls; the dot on the button is lit while anything is injecting |
| The turn waits long after you turn the provider back on | Retry backoff has grown, up to 100 seconds | Wait, or keep outages to about 30 seconds |
| `504 Gateway Time-out` on tmprl-demo.cloud | The Nginx proxy gave up after 60 seconds; the Workflow is still running | Restore the switch; start a new conversation if the reply doesn't appear |
| `LangGraph app is disabled in Demo controls` | The standalone app switch is off | Turn **LangGraph app** on |
| `the previous turn is interrupted; resume it before sending a message` | A standalone turn was cut off | Press **Resume turn**, or **Resume interrupted turn** in Demo controls |
| `Timed out waiting for the agent — check the backend.` after **Approve** | The page stops polling 90 seconds after an approval | Check the Worker and the provider switches; reload to start over |
| The Temporal UI shows repeated Workflow Task failures with `approval request is stale`, `nothing pending`, or `purchase approval is still pending` | An approval or message arrived in a state the Workflow rejects with a plain `RuntimeError` | Press **End workflow** and start a new conversation |
| `Demo access token required` | The API has `DEMO_ACCESS_TOKEN` set | Open the UI with `?token=<token>` once |
| The start screen doesn't load at http://localhost:5173 | Another process holds port 5173 | `lsof -nP -iTCP:5173 -sTCP:LISTEN`, then stop it |

## Keeping this runbook current

The code links point at a fixed commit. When a linked file changes, update its link, line numbers, and snippet together. Before an event, list the linked files that have changed:

```sh
grep -oE 'blob/[0-9a-f]{40}/[^#)]+' RUNBOOK.md | sort -u | while IFS=/ read -r _ sha file; do
  git diff --quiet "$sha" HEAD -- "$file" || echo "changed since ${sha:0:7}: $file"
done
```
