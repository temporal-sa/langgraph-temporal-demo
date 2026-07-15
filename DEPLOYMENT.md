# Deployment notes

The only supported production deployment path is a `DemoProject` resource in
the private `tmprl-demo-cloud-registry` repository. Do not apply Kubernetes,
Helm, Flux, ECR, ingress, certificate, namespace, or Temporal credentials from
this application repository; those are owned by the registry operator.

The deployment preserves the comparison experience. It runs the original
Temporal implementation, standalone LangGraph, and Temporal-backed LangGraph
behind one frontend. The frontend selector sends same-origin requests through
three Nginx prefixes to the matching internal API.

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

3. Add `projects/demo/langgraph-temporal.yaml` to the registry checkout.
4. From the registry root, validate it:

   ```bash
   uv run --isolated --with jsonschema --with pyyaml \
     python scripts/validate_projects.py
   ```

5. Open and merge the registry pull request. The operator builds and tags the
   three app images, frontend, and Postgres image; deploys three APIs, two
   Temporal workers, frontend, and Postgres; injects Temporal Cloud
   credentials; and configures ingress and TLS.
6. Verify `https://langgraph-temporal.tmprl-demo.cloud/healthz` and exercise
   a workflow through the UI.

The two Temporal APIs declare `temporalAccess: true`, and the two Temporal
workers declare `worker: true`; these flags request platform-managed Temporal
access. The standalone LangGraph API has neither because it never connects to
Temporal. The frontend's `servicePort: 80` is the only ingress target and Nginx
maps `/api/temporal`, `/api/langgraph`, and `/api/temporal-langgraph` to their
internal services while stripping the prefix. Ingress authentication protects
the complete demo. Postgres is intentionally ephemeral and re-seeded when
replaced, matching the canonical AI demo pattern.
