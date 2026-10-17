# Serving the trained checkpoint

Checked against Crusoe's official documentation on 2026-10-17. This note is a
controller handoff, not evidence that a model was trained or deployed.

A `fine_tuning.job` with `status: succeeded` and a `fine_tuned_model` identifier
has produced a registered checkpoint. It does not establish that inference is
ready. Crusoe's serverless pool serves base models; a custom LoRA checkpoint
requires a dedicated self-serve deployment. That deployment bills by GPU-hour.
[Official overview](https://docs.crusoecloud.com/self-serve-deployments/overview/index.html).

The [API reference](https://docs.crusoecloud.com/api/) specifies these resources
under `https://api.cloud.crusoe.ai/v1`:

| Method and path | Purpose |
| --- | --- |
| `GET /projects/{project_id}/foundry/selfserve/flavors` | List compatible configurations and hourly prices |
| `POST /projects/{project_id}/foundry/selfserve/deployments` | Create a deployment |
| `GET /projects/{project_id}/foundry/selfserve/deployments/{id}` | Read model, hardware, replicas and status |
| `GET /projects/{project_id}/foundry/selfserve/deployments/{id}/progress` | Read startup progress |
| `GET /projects/{project_id}/foundry/selfserve/deployments/{id}/activity` | Read activity events |
| `DELETE /projects/{project_id}/foundry/selfserve/deployments/{id}` | Remove the dedicated capacity |

Choose a flavor with matching `model_name` and `lora_suitable: true`; inspect
`price_per_hour` and `gpus_per_instance`. The documented creation payload is:

```json
{
  "deployment_name": "aya-sql-l1",
  "fine_tuned_model": "<registered checkpoint ID>",
  "flavor_id": "<compatible flavor ID>",
  "replicas": 1
}
```

The API returns HTTP 202 with `id` and `status`. Poll the resource until `Ready`
before attempting model evaluation.

The [quickstart](https://docs.crusoecloud.com/self-serve-deployments/quickstart/index.html)
documents Bearer authentication with an Intelligence API key and warns that
capacity provisioning can take up to 40 minutes. It uses a different host alias,
`api.crusoecloud.com`, and names the checkpoint field `fine_tuned_model_id`.
These differ from the API reference's host and `fine_tuned_model` field. Resolve
the schema against the current service before relying on an unattended create
request; do not silently treat a rejected request as successful deployment.

When ready, use `https://api.inference.crusoecloud.com/v1` and send the deployment
alias as the Chat Completions `model`, as shown in the quickstart. Keep the
checkpoint ID, deployment ID, alias, selected flavor and live response receipts
together. A second MASS cycle must actually use this new alias; continuing to
call the original base model does not close the weight-update loop.

The official
[PII redaction training example](https://github.com/crusoecloud/crusoe-developer-hub/tree/main/examples/training/pii-redaction)
uses the same training → checkpoint → deployment → evaluation sequence, with
deployment performed through the console. No deployment was created by this
research step.
