# bedrock-core-tools-inventory

AWS Lambda that scans IAM policies and Bedrock agents in one region and writes
five JSON artifacts to S3:

| Artifact | Contents |
|---|---|
| `models.json` | Foundation model catalog |
| `model-bindings.json` | IAM principals with Bedrock invoke permissions |
| `agent-tool-credentials.json` | Agent action-group credential classification |
| `principals.json` | Unique effective principals derived from bindings |
| `manifest.json` | Run metadata and artifact counts |

Each run writes to `{OUTPUT_PREFIX}{account_id}/{timestamp}/`.  
`latest/` is updated only when all five artifacts upload successfully.

---

## Handler

```
handler.handler
```

Runtime: **Python 3.11+**  
All source modules are in `src/`; flatten that directory to the zip root when packaging.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TARGET_REGION` | yes | — | AWS region to scan (e.g. `us-east-1`) |
| `OUTPUT_BUCKET` | yes | — | S3 bucket where artifacts are written |
| `OUTPUT_PREFIX` | no | `runs/` | S3 key prefix for run artifacts |
| `ACCOUNT_ID` | no | resolved via STS | AWS account ID; set explicitly to avoid the STS call |

---

## Packaging

```bash
pip install -r requirements.txt -t package/
cp src/*.py package/
cd package && zip -r ../bedrock-core-tools-inventory.zip . && cd ..
```

The resulting `bedrock-core-tools-inventory.zip` is ready to upload.

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```
