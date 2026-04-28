# bedrock-core-tools-inventory

Scheduled AWS Lambda that produces JSON inventory artifacts covering four IAM governance
surfaces for Amazon Bedrock. These artifacts are consumed by the
[AWS Bedrock OpenICF Connector](https://github.com/srallapally/aws-bedrock-connector)
during PingOne IDM / OpenIDM reconciliation.

**This Lambda must be deployed and producing output before the connector can populate
`agentPrincipals`, `agentIdentityBinding` objects, or `agentToolCredentials` objects.**

---

## Table of Contents

1. [What It Produces](#1-what-it-produces)
2. [Prerequisites](#2-prerequisites)
3. [Deployment](#3-deployment)
   - 3.1 [Create the Deployment Bucket](#31-create-the-deployment-bucket)
   - 3.2 [Create the IAM Execution Role](#32-create-the-iam-execution-role)
   - 3.3 [Package the Lambda](#33-package-the-lambda)
   - 3.4 [Upload and Create the Lambda Function](#34-upload-and-create-the-lambda-function)
   - 3.5 [Create the EventBridge Schedule](#35-create-the-eventbridge-schedule)
4. [Verification](#4-verification)
5. [Environment Variables](#5-environment-variables)
6. [IAM Permissions Reference](#6-iam-permissions-reference)
7. [S3 Artifact Layout](#7-s3-artifact-layout)
8. [Output Schemas](#8-output-schemas)
   - 8.1 [`agent-bindings.json`](#81-agent-bindingsjson)
   - 8.2 [`agent-tool-credentials.json`](#82-agent-tool-credentialsjson)
   - 8.3 [`model-bindings.json`](#83-model-bindingsjson)
   - 8.4 [`models.json`](#84-modelsjson)
   - 8.5 [`principals.json`](#85-principalsjson)
   - 8.6 [`manifest.json`](#86-manifestjson)
9. [Updating the Lambda Code](#9-updating-the-lambda-code)
10. [Error Handling and Failure Modes](#10-error-handling-and-failure-modes)
11. [Operational Considerations](#11-operational-considerations)
12. [Architecture Notes](#12-architecture-notes)

---

## 1. What It Produces

The Lambda runs on a 15-minute EventBridge schedule and writes six JSON artifacts to S3
under a timestamped run prefix and a stable `latest/` prefix. The connector reads from
`latest/`.

| Artifact | Surface covered |
|---|---|
| `agent-bindings.json` | IAM principals (roles, users, group-inherited) with `bedrock:InvokeAgent` permission |
| `agent-tool-credentials.json` | Executor classification for every agent action group — what credential type and ARN each action group uses |
| `model-bindings.json` | IAM principals with `bedrock:InvokeModel` / `bedrock:Converse` / equivalent permissions |
| `models.json` | Foundation model catalog from `bedrock:ListFoundationModels` |
| `principals.json` | Deduplicated IAM principal index derived from `model-bindings.json` |
| `manifest.json` | Run metadata — counts, warning conditions, timestamp |

The Lambda makes no writes to IAM or Bedrock. It is a read-only data collection and
normalization pipeline.

---

## 2. Prerequisites

- AWS CLI installed and configured with credentials sufficient to create IAM roles,
  Lambda functions, S3 buckets, and EventBridge rules
- Python 3.11+, `pip`, and `zip` installed locally
- An S3 bucket to receive the inventory artifacts (`bedrock-core-inventory` by default —
  create it before deploying if it does not exist)
- A separate S3 bucket to stage the Lambda ZIP during deployment

**Create the inventory bucket if it does not exist:**

```bash
aws s3api create-bucket \
  --bucket bedrock-core-inventory \
  --region us-east-1

aws s3api put-public-access-block \
  --bucket bedrock-core-inventory \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

---

## 3. Deployment

### 3.1 Create the Deployment Bucket

This bucket is used only to stage the Lambda ZIP. It is separate from the inventory
output bucket.

```bash
aws s3api create-bucket \
  --bucket bedrock-core-tools-inventory-deploy \
  --region us-east-1

aws s3api put-public-access-block \
  --bucket bedrock-core-tools-inventory-deploy \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

> S3 bucket names are globally unique. If `bedrock-core-tools-inventory-deploy` is
> taken, suffix with your account ID:
> `bedrock-core-tools-inventory-deploy-470686885243`

### 3.2 Create the IAM Execution Role

**Create the trust policy:**

```bash
cat > /tmp/lambda-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
  --role-name bedrock-core-inventory-lambda-role \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
  --description "Execution role for bedrock-core-tools-inventory Lambda"
```

Save the `Role.Arn` from the output.
Format: `arn:aws:iam::<account-id>:role/bedrock-core-inventory-lambda-role`

**Attach the CloudWatch Logs managed policy:**

```bash
aws iam attach-role-policy \
  --role-name bedrock-core-inventory-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

**Create and attach the custom inventory policy:**

```bash
cat > /tmp/inventory-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "IAMReadForBindings",
      "Effect": "Allow",
      "Action": [
        "iam:ListRoles",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListUsers",
        "iam:ListUserPolicies",
        "iam:GetUserPolicy",
        "iam:ListAttachedUserPolicies",
        "iam:ListGroupsForUser",
        "iam:ListGroupPolicies",
        "iam:GetGroupPolicy",
        "iam:ListAttachedGroupPolicies",
        "iam:GetPolicy",
        "iam:GetPolicyVersion"
      ],
      "Resource": "*"
    },
    {
      "Sid": "BedrockRead",
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock:ListAgents",
        "bedrock:GetAgent",
        "bedrock:ListAgentActionGroups",
        "bedrock:GetAgentActionGroup"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaReadForToolCredentials",
      "Effect": "Allow",
      "Action": "lambda:GetFunction",
      "Resource": "*"
    },
    {
      "Sid": "S3WriteInventory",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:CopyObject"
      ],
      "Resource": "arn:aws:s3:::bedrock-core-inventory/*"
    },
    {
      "Sid": "STSCallerIdentity",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name bedrock-core-inventory-lambda-role \
  --policy-name BedrockCoreInventoryPolicy \
  --policy-document file:///tmp/inventory-policy.json
```

Wait ~10 seconds for IAM propagation before proceeding.

### 3.3 Package the Lambda

```bash
git clone https://github.com/srallapally/bedrock-core-tools-inventory.git
cd bedrock-core-tools-inventory

pip install -r requirements.txt -t package/
cp src/*.py package/

cd package
zip -r ../bedrock-core-tools-inventory.zip .
cd ..
```

Verify the handler is at the root of the ZIP (not under a subdirectory):

```bash
unzip -l bedrock-core-tools-inventory.zip | grep handler.py
```

Expected: `handler.py` with no path prefix.

### 3.4 Upload and Create the Lambda Function

```bash
aws s3 cp bedrock-core-tools-inventory.zip \
  s3://bedrock-core-tools-inventory-deploy/bedrock-core-tools-inventory.zip \
  --region us-east-1

aws lambda create-function \
  --function-name bedrock-core-tools-inventory \
  --runtime python3.11 \
  --handler handler.handler \
  --role arn:aws:iam::<account-id>:role/bedrock-core-inventory-lambda-role \
  --code S3Bucket=bedrock-core-tools-inventory-deploy,S3Key=bedrock-core-tools-inventory.zip \
  --timeout 900 \
  --memory-size 256 \
  --environment "Variables={
    REGION=us-east-1,
    CORE_INVENTORY_BUCKET=bedrock-core-inventory,
    OUTPUT_PREFIX=bedrock-core-inventory/,
    ACCOUNT_ID=<account-id>
  }" \
  --region us-east-1
```

Save the `FunctionArn` from the output.
Format: `arn:aws:lambda:us-east-1:<account-id>:function:bedrock-core-tools-inventory`

### 3.5 Create the EventBridge Schedule

```bash
# Create the rule
aws events put-rule \
  --name bedrock-core-inventory-schedule \
  --schedule-expression "rate(15 minutes)" \
  --state ENABLED \
  --description "Triggers bedrock-core-tools-inventory every 15 minutes" \
  --region us-east-1
```

Save the `RuleArn` from the output.

```bash
# Add the Lambda as target
aws events put-targets \
  --rule bedrock-core-inventory-schedule \
  --targets "Id=LambdaTarget,Arn=<FunctionArn>" \
  --region us-east-1

# Grant EventBridge permission to invoke the Lambda
aws lambda add-permission \
  --function-name bedrock-core-tools-inventory \
  --statement-id EventBridgeInvoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn <RuleArn> \
  --region us-east-1
```

---

## 4. Verification

**Trigger a manual invocation:**

```bash
aws lambda invoke \
  --function-name bedrock-core-tools-inventory \
  --payload '{}' \
  --region us-east-1 \
  /tmp/response.json && cat /tmp/response.json
```

Expected response:

```json
{"statusCode": 200, "run_prefix": "bedrock-core-inventory/runs/20260427T123456Z/"}
```

A `statusCode` of 500 means the Lambda ran but failed internally. Check CloudWatch Logs
before investigating S3.

**Tail CloudWatch Logs:**

```bash
aws logs tail /aws/lambda/bedrock-core-tools-inventory \
  --follow \
  --region us-east-1
```

Look for `uploaded agent-bindings.json` and `uploaded agent-tool-credentials.json`.
The final log line should contain `"statusCode": 200`.

**Verify S3 output:**

```bash
# Confirm latest/ is populated with all six artifacts
aws s3 ls s3://bedrock-core-inventory/latest/ --region us-east-1
```

Expected — six files:

```
agent-bindings.json
agent-tool-credentials.json
manifest.json
model-bindings.json
models.json
principals.json
```

**Inspect individual artifacts:**

```bash
# Agent bindings — confirm bindings array is non-empty if InvokeAgent policies exist
aws s3 cp s3://bedrock-core-inventory/latest/agent-bindings.json - \
  --region us-east-1 | python3 -m json.tool

# Tool credentials — confirm credentialType values are present
aws s3 cp s3://bedrock-core-inventory/latest/agent-tool-credentials.json - \
  --region us-east-1 | python3 -m json.tool

# Manifest — confirm counts are non-zero and generatedAt is recent
aws s3 cp s3://bedrock-core-inventory/latest/manifest.json - \
  --region us-east-1 | python3 -m json.tool
```

---

## 5. Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `REGION` | `AWS_REGION` → `us-east-1` | Yes | AWS region for all Bedrock and IAM API calls. Deploy one Lambda per target region. |
| `CORE_INVENTORY_BUCKET` | `bedrock-core-inventory` | Yes | S3 bucket name for artifact output. Bucket name only — no `s3://` prefix, no trailing slash. |
| `OUTPUT_PREFIX` | `bedrock-core-inventory/` | No | S3 key prefix prepended to `runs/` and `latest/` paths. |
| `ACCOUNT_ID` | STS fallback | No | Set to avoid a `sts:GetCallerIdentity` call on each cold start. |
| `IAM_INTER_CALL_DELAY_MS` | `0` | No | Milliseconds to sleep between IAM read calls. Set to 100–200 for accounts with >2,000 IAM roles to reduce throttling risk. |

---

## 6. IAM Permissions Reference

The Lambda execution role requires the following permissions. The policy document in
[Section 3.2](#32-create-the-iam-execution-role) reflects this list.

| Permission | Scope | Purpose |
|---|---|---|
| `iam:ListRoles` | `*` | Role enumeration |
| `iam:ListRolePolicies` | `*` | Inline role policy listing |
| `iam:GetRolePolicy` | `*` | Inline role policy document fetch |
| `iam:ListAttachedRolePolicies` | `*` | Managed role policy listing |
| `iam:ListUsers` | `*` | User enumeration |
| `iam:ListUserPolicies` | `*` | Inline user policy listing |
| `iam:GetUserPolicy` | `*` | Inline user policy document fetch |
| `iam:ListAttachedUserPolicies` | `*` | Managed user policy listing |
| `iam:ListGroupsForUser` | `*` | Group membership enumeration per user |
| `iam:ListGroupPolicies` | `*` | Inline group policy listing |
| `iam:GetGroupPolicy` | `*` | Inline group policy document fetch |
| `iam:ListAttachedGroupPolicies` | `*` | Managed group policy listing |
| `iam:GetPolicy` | `*` | Managed policy default version resolution |
| `iam:GetPolicyVersion` | `*` | Managed policy document fetch |
| `bedrock:ListFoundationModels` | `*` | Foundation model catalog |
| `bedrock:ListAgents` | `*` | Agent enumeration |
| `bedrock:GetAgent` | `*` | Agent service role ARN — required to populate `agentServiceRoleArn` |
| `bedrock:ListAgentActionGroups` | `*` | Action group enumeration per agent |
| `bedrock:GetAgentActionGroup` | `*` | Executor type and credential classification |
| `lambda:GetFunction` | `*` | Lambda execution role ARN resolution for `LAMBDA_EXECUTION_ROLE` action groups |
| `s3:PutObject` | `arn:aws:s3:::bedrock-core-inventory/*` | Artifact upload to run prefix |
| `s3:CopyObject` | `arn:aws:s3:::bedrock-core-inventory/*` | `latest/` promotion |
| `s3:GetObject` | `arn:aws:s3:::bedrock-core-inventory/*` | Internal verification reads |
| `sts:GetCallerIdentity` | `*` | Account ID resolution (avoidable via `ACCOUNT_ID` env var) |

---

## 7. S3 Artifact Layout

```
s3://{CORE_INVENTORY_BUCKET}/
    bedrock-core-inventory/
        runs/{YYYYMMDDTHHMMSSZ}/     ← immutable audit trail per run
            agent-bindings.json
            agent-tool-credentials.json
            model-bindings.json
            models.json
            principals.json
            manifest.json
        latest/                      ← stable read path for the Java connector
            (same six files)
```

`latest/` is atomic: all six `PutObject` calls to the run prefix succeed before any
`CopyObject` to `latest/` runs. A failed run leaves the previous `latest/` content
unchanged.

Run-specific prefixes are never deleted by the Lambda. Configure an S3 lifecycle rule
on the `runs/` prefix if retention limits are required.

The Java connector reads from:
- `latest/agent-bindings.json`
- `latest/agent-tool-credentials.json`

---

## 8. Output Schemas

### 8.1 `agent-bindings.json`

Envelope object containing a flat array of IAM-to-agent binding records.

**Envelope:**

```json
{
  "accountId": "470686885243",
  "region": "us-east-1",
  "generatedAt": "2026-04-27T12:00:00+00:00",
  "bindings": [ ... ]
}
```

**Binding record fields:**

| Field | Type | Nullable | Description |
|---|---|---|---|
| `agentArn` | string | Yes | Full agent ARN; `null` for wildcard resources |
| `agentVersion` | string | Yes | Always `null` in current implementation |
| `aliasArn` | string | Yes | Full alias ARN; `null` for bare `agent/` ARNs and wildcards |
| `principalType` | string | No | `ROLE` or `USER` |
| `principalName` | string | No | IAM role or user name |
| `principalArn` | string | No | Effective principal ARN — user ARN even for group-inherited bindings |
| `principalAccountId` | string | No | AWS account ID of the principal |
| `wildcard` | boolean | No | `true` when the IAM resource was `*` or a wildcard ARN |
| `conditionJson` | string | Yes | Serialized IAM condition block; `null` when no condition |
| `bindingOrigin` | string | No | `DIRECT_ROLE_POLICY`, `DIRECT_USER_POLICY`, or `GROUP_INHERITED` |
| `sourcePrincipalArn` | string | Yes | Group ARN when `GROUP_INHERITED`; same as `principalArn` otherwise |
| `sourcePrincipalType` | string | Yes | `group` when `GROUP_INHERITED` |
| `sourcePrincipalName` | string | Yes | Group name when `GROUP_INHERITED` |

### 8.2 `agent-tool-credentials.json`

Flat array. One record per action group across all agents.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | string | No | `tc-{sha256[:16]}` of `agentId\|actionGroupId` — stable primary key |
| `agentId` | string | No | Bedrock agent ID |
| `agentArn` | string | No | Full agent ARN |
| `agentServiceRoleArn` | string | No | IAM role the agent assumes when invoking this action group |
| `actionGroupId` | string | No | Action group ID |
| `actionGroupName` | string | No | Action group name |
| `actionGroupState` | string | No | `ENABLED` or `DISABLED` |
| `credentialType` | string | No | `LAMBDA_EXECUTION_ROLE` \| `S3_READ` \| `CONFLUENCE_SECRET` \| `NONE` |
| `credentialRef` | string | Yes | ARN identifying the credential surface — never the credential value |
| `apiSchemaSource` | string | Yes | `S3`, `INLINE`, or `null` |
| `functionSchema` | boolean | No | `true` when using function-definition schema (not OpenAPI) |
| `accountId` | string | No | AWS account ID |
| `region` | string | No | AWS region |
| `lambdaExecutionRoleArn` | string | Yes | IAM execution role ARN of the Lambda function. Populated for `LAMBDA_EXECUTION_ROLE` action groups only; `null` for all other types. |

**`credentialType` values explained:**

| Value | Meaning |
|---|---|
| `LAMBDA_EXECUTION_ROLE` | Action group invokes a Lambda function. The agent's `agentServiceRoleArn` is the IAM boundary. `credentialRef` is the Lambda ARN. `lambdaExecutionRoleArn` is the Lambda function's own IAM role. |
| `S3_READ` | Action group reads an OpenAPI schema from S3. `credentialRef` is the S3 bucket ARN. |
| `CONFLUENCE_SECRET` | Action group uses a Confluence datasource. `credentialRef` is the Secrets Manager secret ARN. |
| `NONE` | Action group uses Return Control — no executor invoked; control returned to the caller. |

### 8.3 `model-bindings.json`

Flat array of IAM-to-model binding records for principals with `bedrock:InvokeModel`,
`bedrock:Converse`, `bedrock:ConverseStream`, `bedrock:InvokeModelWithResponseStream`, or
`bedrock:InvokeInlineAgent` permissions.

Key fields: `id` (`mb-{sha256[:16]}`), `principalArn`, `principalType`, `modelArn`,
`scopeType` (`MODEL`, `MODEL_WILDCARD`, `PROVISIONED_MODEL`, `CUSTOM_MODEL`,
`ACCOUNT_REGION_WILDCARD`), `wildcard`, `confidence` (`MEDIUM` for static scan; `LOW`
for conditional), `bindingOrigin`, `sourceTag`, `conditionJson`.

### 8.4 `models.json`

Array of foundation model objects from `bedrock:ListFoundationModels`. Fields: `modelId`,
`modelArn`, `modelName`, `providerName`, `inputModalities`, `outputModalities`,
`responseStreamingSupported`, `inferenceTypesSupported`, `customizationsSupported`,
`accountId`, `region`.

### 8.5 `principals.json`

Deduplicated IAM principals from `model-bindings.json`. One entry per unique
`principalArn`, sorted by ARN. Fields: `principalArn`, `principalType`, `principalName`,
`principalAccountId`, `bindingCount`.

### 8.6 `manifest.json`

Single object per run. Key fields:

| Field | Description |
|---|---|
| `generatedAt` | UTC ISO-8601 timestamp |
| `schemaVersion` | Always `1.0` |
| `accountId` | AWS account ID |
| `region` | AWS region scanned |
| `modelCount` | Records in `models.json` |
| `modelBindingCount` | Records in `model-bindings.json` |
| `agentBindingCount` | Records in `agent-bindings.json` `bindings` array |
| `agentToolCredentialCount` | Records in `agent-tool-credentials.json` |
| `principalCount` | Records in `principals.json` |
| `warnings` | Array of warning condition strings |

**Warning conditions:**

| Warning | Meaning |
|---|---|
| `NO_MODEL_BINDINGS_FOUND` | No principals have model-invocation permissions |
| `WILDCARD_BINDINGS_PRESENT` | One or more model bindings use wildcard resources |
| `CONDITIONAL_BINDINGS_PRESENT` | One or more model bindings have IAM condition blocks |
| `NO_AGENT_BINDINGS_FOUND` | No principals have `bedrock:InvokeAgent` permission |

---

## 9. Updating the Lambda Code

After any change to `src/`:

```bash
# Re-package
rm -rf package bedrock-core-tools-inventory.zip
pip install -r requirements.txt -t package/
cp src/*.py package/
cd package && zip -r ../bedrock-core-tools-inventory.zip . && cd ..

# Upload
aws s3 cp bedrock-core-tools-inventory.zip \
  s3://bedrock-core-tools-inventory-deploy/bedrock-core-tools-inventory.zip \
  --region us-east-1

# Deploy
aws lambda update-function-code \
  --function-name bedrock-core-tools-inventory \
  --s3-bucket bedrock-core-tools-inventory-deploy \
  --s3-key bedrock-core-tools-inventory.zip \
  --region us-east-1
```

---

## 10. Error Handling and Failure Modes

### Fatal — Lambda returns 500, `latest/` unchanged

| Failure | Effect |
|---|---|
| `bedrock:ListFoundationModels` fails | Lambda aborts; retry on next schedule |
| `iam:ListRoles` or `iam:ListUsers` fails | Lambda aborts; retry on next schedule |
| `bedrock:ListAgents` fails | Lambda aborts; retry on next schedule |
| Any `s3:PutObject` fails | Lambda aborts; previous `latest/` unchanged |

### Recoverable — WARNING logged, scan continues

| Failure | Effect |
|---|---|
| Per-role IAM policy fetch fails | Policy skipped; binding may be absent until next run |
| Per-user IAM policy fetch fails | Policy skipped |
| `bedrock:GetAgent` fails for one agent | Agent skipped entirely from tool credentials output |
| `bedrock:ListAgentActionGroups` fails for one agent | Empty action group list for that agent |
| `bedrock:GetAgentActionGroup` fails for one action group | Sparse record emitted with `id`, `agentId`, `actionGroupId` only |
| `lambda:GetFunction` fails for one function | `lambdaExecutionRoleArn: null` on that record |

### IAM Throttling

IAM `GetPolicyVersion` has a default rate limit of 5 TPS. At 500 roles with 3 attached
policies each, approximately 1,500 `GetPolicyVersion` calls are made per run. Throttled
calls are retried up to 5 times with full-jitter exponential backoff (initial delay 1s,
max 30s cap). For accounts with >2,000 roles, set `IAM_INTER_CALL_DELAY_MS=100` to
reduce sustained throughput.

---

## 11. Operational Considerations

**Multi-region.** Deploy one Lambda instance per target AWS region. Records in each
run's artifacts carry the `region` field of the instance that produced them. Do not mix
artifacts from different regions under the same `latest/` prefix.

**Freshness monitoring.** Alert when `manifest.json` `generatedAt` is more than two
schedule intervals old (>30 minutes for a 15-minute schedule). The run-specific prefixes
provide a full audit trail; the Lambda never deletes historical runs.

**Connector cache alignment.** The Java connector caches S3 artifacts for
`bindingsCacheTtlSeconds` (default 300s). The maximum staleness seen by the connector is
`bindingsCacheTtlSeconds + Lambda-schedule-interval` — approximately 20 minutes at
defaults. Reduce `bindingsCacheTtlSeconds` if fresher data is required; reduce the
EventBridge schedule interval with caution (sub-5-minute schedules risk IAM rate limits
at large account sizes).

**Resource summary:**

| Resource | Name |
|---|---|
| Lambda function | `bedrock-core-tools-inventory` |
| Lambda execution role | `bedrock-core-inventory-lambda-role` |
| Deployment bucket | `bedrock-core-tools-inventory-deploy` |
| Inventory bucket | `bedrock-core-inventory` |
| EventBridge rule | `bedrock-core-inventory-schedule` |
| Schedule | Every 15 minutes |
| Handler | `handler.handler` |
| Runtime | Python 3.11 |
| Timeout | 900s |
| Memory | 256 MB |

---

## 12. Architecture Notes

**Why IAM scanning is offline.** IAM policy evaluation at account scale requires hundreds
to thousands of API calls before a single binding is resolved. Making this evaluation live
inside IDM reconciliation would couple reconciliation latency to IAM throughput and expose
the reconciliation critical path to IAM rate limits. The Lambda pays this cost on a
15-minute schedule and caches results in S3.

**Why roles and users are listed once.** `list_roles` and `list_users` are called once
per invocation and the results shared between the model binding scan and the agent binding
scan. This avoids duplicate IAM list calls and prevents inconsistencies between the two
scans from IAM state changes mid-invocation.

**Why `agentVersion=DRAFT` for action group enumeration.** DRAFT always reflects the
current working agent configuration. Enumerating published versions would multiply API
calls by version count with diminishing governance value.

**Why `latest/` is atomic.** All six `PutObject` calls to the run prefix succeed before
any `CopyObject` to `latest/` runs. A partial failure leaves `latest/` unchanged. The
Java connector always reads a complete, coherent artifact set.

**Why `principalArn` is the user ARN on group-inherited bindings.** The
governance-relevant fact is which user has access, not which group grants it.
`sourcePrincipalArn` carries the group ARN for lineage tracing. Wildcard bindings use
`principalArn` of the role or user; `agentArn`/`aliasArn` are `null`.
