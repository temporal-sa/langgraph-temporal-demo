# Deployment notes

The only supported production deployment path is a `DemoProject` resource in
the private `tmprl-demo-cloud-registry` repository. Do not apply Kubernetes,
Helm, Flux, ECR, ingress, certificate, namespace, or Temporal credentials from
this application repository; those are owned by the registry operator.

The production application is the `python-langgraph-temporal` implementation.
The original Temporal and standalone LangGraph variants remain available in
the source-based local comparison environment but are not production
components.

## Onboarding sequence

1. Make the source repository available at
   `https://github.com/temporal-sa/langgraph-temporal-demo`.
2. Create these JSON secrets in AWS Secrets Manager, account `429214323166`,
   region `us-west-1`:

   - `tmprl-dem-cld/langgraph-temporal/llm-credentials` with
     `OPENAI_API_KEY`.
   - `tmprl-dem-cld/langgraph-temporal/database` with `POSTGRES_USER`,
     `POSTGRES_PASSWORD`, and an operator-network URL such as
     `postgresql://demo:<url-encoded-password>@postgres:5432/chinook` in
     `DB_URL`.
   - `tmprl-dem-cld/langgraph-temporal/demo-access` with
     `DEMO_ACCESS_TOKEN`.

3. Add `projects/demo/langgraph-temporal.yaml` to the registry checkout.
4. From the registry root, validate it:

   ```bash
   uv run --isolated --with jsonschema --with pyyaml \
     python scripts/validate_projects.py
   ```

5. Open and merge the registry pull request. The operator builds and tags the
   app, frontend, and Postgres images; deploys separate frontend, backend,
   worker, and Postgres components; injects Temporal Cloud credentials; and
   configures ingress and TLS.
6. Verify `https://langgraph-temporal.tmprl-demo.cloud/api/health` and exercise
   a workflow through the UI.

The backend declares `temporalAccess: true`, and the worker declares
`worker: true`; these flags are what request platform-managed Temporal access.
The frontend's `servicePort: 80` makes it the public catch-all, with nginx
proxying `/api` to `http://backend:8000`. Postgres is intentionally ephemeral
and re-seeded when replaced, matching the canonical AI demo pattern.
