# AWS Bedrock Core Offline Inventory — Design Specification

_Version: 1.1 | 2026-04-19_

_Revision notes: downgraded confidence model (no HIGH without simulation); added `agentServiceRoleArn` to credential records; fixed dedup key to use `sourcePrincipalArn`; added retry/backoff spec for IAM; added explicit region scope definition._

---

## 1. Executive Summary

The Bedrock Core Offline Inventory is a scheduled AWS Lambda function that produces JSON artifact files describing two governance surfaces that cannot be economically evaluated live during each identity-governance reconciliation cycle:

- **Model-invocation identity bindings** — which IAM principals (roles, users, and users inheriting via groups) hold permissions to invoke Amazon Bedrock foundation models directly via `bedrock:InvokeModel`, `bedrock:Converse`, and related actions.
- **Agent tool credentials** — for each Bedrock agent, which action groups are configured, which backend each action group calls, and what credential or authentication mechanism the agent uses to reach that backend.

The existing Bedrock Agents Lambda (`lambda_function.py`) covers who-can-invoke-agent (`bedrock:InvokeAgent`). This system covers the complementary surfaces: who can invoke models directly, and what credentials the agents themselves exercise when invoking tools.

The job runs on a schedule (recommended: every 15 minutes to hourly), writes five JSON artifacts to Amazon S3 under a timestamped run prefix and a stable `latest/` prefix, and returns. It makes no writes to IAM or Bedrock — it is a read-only data collection and normalization pipeline.

---

## 2. System Context

### 2.1 Relationship to the Existing Agent Inventory Lambda

The existing `lambda_function.py` scans IAM for `bedrock:InvokeAgent` bindings and inventories agent aliases. This new Lambda is additive — it runs independently, writes to a separate S3 bucket, and covers two gaps the agent lambda does not address:

| Surface | Existing Agent Lambda | This Lambda (Core Inventory) |
|---|---|---|
| Who can invoke an agent (InvokeAgent) | Yes — `identity-bindings.json` | No |
| Who can invoke a model directly (InvokeModel / Converse) | No | Yes — `model-bindings.json` |
| Which models exist (foundation model catalog) | No | Yes — `models.json` |
| Which tools an agent can call and with what credential | No | Yes — `agent-tool-credentials.json` |
| Agent alias inventory | Yes — `agent-aliases.json` | No |

### 2.2 Execution Identity

The Lambda execution role is separate from the role used by the agent inventory Lambda. It requires read-only IAM permissions (identical scan surface) plus `bedrock:ListFoundationModels`, `bedrock:ListAgents`, `bedrock:ListAgentActionGroups`, and `bedrock:GetAgentActionGroup`. It holds no `bedrock:InvokeModel` or `bedrock:InvokeAgent` permissions — it describes resources, never invokes them.

Authentication is via the Lambda execution role using standard AWS SDK credential resolution (environment variables on the managed runtime). No long-lived keys are stored in the function.

---

## 3. Architecture

### 3.1 Component Diagram

```
EventBridge (schedule)
    |
    v
Lambda: bedrock-core-inventory
    |-- collect_foundation_models()          --> bedrock:ListFoundationModels
    |-- scan_iam_for_model_bindings()        --> IAM list/get (roles, users, groups)
    |-- collect_agent_tool_credentials()     --> bedrock:ListAgents
    |                                            bedrock:ListAgentActionGroups
    |                                            bedrock:GetAgentActionGroup
    |-- normalize_model_bindings()
    |-- normalize_tool_credentials()
    |-- write_artifacts()
          |-- s3://<bucket>/bedrock-core-inventory/runs/<timestamp>/
          |       models.json
          |       model-bindings.json
          |       agent-tool-credentials.json
          |       principals.json
          |       manifest.json
          |
          +-- s3://<bucket>/bedrock-core-inventory/latest/
                  (same five files, promoted after run prefix succeeds)
```

### 3.2 Live vs. Offline Split Rationale

IAM policy evaluation requires listing all roles, all users, all group memberships, all inline policies, and all attached managed policies. At account scale this can exceed 200 API calls before a single binding is resolved. Making this evaluation live inside an IDM reconciliation connector would couple reconciliation latency to IAM API throughput and expose the reconciliation path to IAM rate limits. The offline Lambda pays this cost outside the reconciliation critical path and caches results in S3 for the connector to read.

Agent tool credential collection similarly requires enumerating action groups per agent and fetching each action group's executor configuration. This is a nested pagination problem (agents × action groups) that is expensive at scale and inappropriate for the live connector path.

---

## 4. Identity Model

### 4.1 Lambda Execution Role

| Property | Value |
|---|---|
| Identity type | AWS IAM role (Lambda execution role) |
| Auth method | AWS SDK credential resolution on managed Lambda runtime |
| Credential storage | None — role assumed automatically by Lambda service |

**Required permissions:**

| API Surface | Permission | Scope | Why |
|---|---|---|---|
| IAM | `iam:ListRoles`, `iam:ListRolePolicies`, `iam:GetRolePolicy`, `iam:ListAttachedRolePolicies` | Account | Model-binding scan — roles |
| IAM | `iam:ListUsers`, `iam:ListUserPolicies`, `iam:GetUserPolicy`, `iam:ListAttachedUserPolicies` | Account | Model-binding scan — users |
| IAM | `iam:ListGroupsForUser`, `iam:ListGroupPolicies`, `iam:GetGroupPolicy`, `iam:ListAttachedGroupPolicies` | Account | Model-binding scan — group inheritance |
| IAM | `iam:GetPolicy`, `iam:GetPolicyVersion` | Account | Resolve managed policy documents |
| Bedrock | `bedrock:ListFoundationModels` | Account | Foundation model catalog |
| Bedrock | `bedrock:ListAgents` | Account | Agent enumeration for tool credential scan |
| Bedrock | `bedrock:ListAgentActionGroups` | Agent | Action group enumeration per agent |
| Bedrock | `bedrock:GetAgentActionGroup` | Action Group | Action group executor configuration |
| STS | `sts:GetCallerIdentity` | Account | Account ID resolution (fallback to `ACCOUNT_ID` env var) |
| S3 | `s3:PutObject` | Bucket (`bedrock-core-inventory` bucket only) | Artifact upload |

---

## 5. API Call Inventory

### 5.1 IAM API — Model-Binding Scan

The model-binding scan uses the identical IAM traversal pattern as the existing agent Lambda. The same paginator helpers (`scan_inline_policies`, `scan_attached_policies`) are reused. The only difference is the action filter: instead of `includes_bedrock_invoke_agent()`, the model scan uses a new `includes_bedrock_invoke_model()` predicate.

**Actions matched by `includes_bedrock_invoke_model()`:**

| IAM Action | Included |
|---|---|
| `bedrock:InvokeModel` | Yes |
| `bedrock:InvokeModelWithResponseStream` | Yes |
| `bedrock:Converse` | Yes |
| `bedrock:ConverseStream` | Yes |
| `bedrock:InvokeInlineAgent` | Yes |
| `bedrock:*` | Yes |
| `*` | Yes |
| `bedrock:InvokeAgent` | No — covered by agent lambda |
| `bedrock:ListFoundationModels` | No — not an invocation action |

Principal scan order: (1) IAM roles — inline then attached policies. (2) IAM users — direct inline, direct attached, then group-inherited inline and attached. Group-inherited bindings record the user as `principalArn` and carry group lineage fields (`sourcePrincipalType`, `sourcePrincipalName`, `sourcePrincipalArn`) identical to the agent lambda pattern.

### 5.2 Bedrock API — Foundation Model Catalog

Endpoint: `bedrock:ListFoundationModels`. Called against the single region specified by the `REGION` env var.

**Pagination.** As of the current API version, `ListFoundationModels` returns all models in a single response with no `nextToken`. The implementation must not rely on this. Use a defensive pagination loop that follows `nextToken` if present, consistent with all other list calls in this Lambda. If AWS introduces pagination in a future API version, the loop will handle it transparently; if not, it exits after the first page. A single-response assumption would break silently when pagination is added.

**Region scope.** The Lambda operates against exactly one AWS region per invocation, determined at startup from `REGION` → `AWS_REGION` → `us-east-1`. The Bedrock model catalog, agent action group enumeration, and IAM binding scan all use this single region. Cross-region inventory requires deploying one Lambda instance per target region — there is no multi-region mode in v1. The `region` field on every output record reflects the region the Lambda ran against. Downstream consumers must not assume records from different regions appear in the same artifact.

**Fields used per model:**

| API Field | Purpose |
|---|---|
| `modelId` | Primary identifier — used as `id` in `models.json` |
| `modelName` | Human-readable name |
| `providerName` | Model provider (e.g. Anthropic, Amazon, Meta) |
| `modelArn` | Full model ARN — used as `resourceName` |
| `inputModalities` | Input types supported (`TEXT`, `IMAGE`, `EMBEDDING`) |
| `outputModalities` | Output types supported |
| `responseStreamingSupported` | Whether streaming is available |
| `inferenceTypesSupported` | `ON_DEMAND`, `PROVISIONED`, or both |
| `customizationsSupported` | `FINE_TUNING`, `CONTINUED_PRE_TRAINING` |

### 5.3 Bedrock API — Agent Action Group Enumeration

This is a nested pagination: for each agent, enumerate action groups; for each action group, fetch full configuration.

**Step 1 — List agents:** `bedrock:ListAgents`, paginated via `nextToken`. Fields used: `agentId`, `agentName`, `agentStatus`, `agentArn`.

**Step 2 — List action groups per agent:** `bedrock:ListAgentActionGroups(agentId=X, agentVersion=DRAFT)`, paginated via `nextToken`. Fields used: `actionGroupId`, `actionGroupName`, `actionGroupState`, `actionGroupExecutor`.

**Step 3 — Get action group detail:** `bedrock:GetAgentActionGroup(agentId=X, actionGroupId=Y, agentVersion=DRAFT)`. Returns full executor configuration including Lambda ARN, API schema (S3 or inline), authentication configuration, and Confluence datasource configuration where applicable.

**Error behavior:** `ListAgents` failure raises and aborts the Lambda. `ListAgentActionGroups` failure for a single agent logs WARNING and emits an empty action group list for that agent; the Lambda continues. `GetAgentActionGroup` failure for a single action group logs WARNING and emits a sparse credential record; the Lambda continues.

### 5.4 S3 — Artifact Upload

Identical write pattern to the existing agent Lambda. Run-specific prefix is written first. `latest/` prefix is promoted only after all five run artifacts succeed. Any `PutObject` failure raises `ClientError`, which propagates and causes the Lambda to return `statusCode 500`.

---

## 6. IAM Binding Normalization

### 6.1 Resource Scoping

Bedrock model ARNs have a distinct structure from agent ARNs. The account segment is empty for foundation models (the model namespace is global within a region). The parser must handle this:

| ARN Pattern | `scopeType` | Notes |
|---|---|---|
| `arn:aws:bedrock:{region}::foundation-model/{modelId}` | `MODEL` | Empty account segment — expected |
| `arn:aws:bedrock:{region}:{account}:provisioned-model/{id}` | `PROVISIONED_MODEL` | Account-scoped |
| `arn:aws:bedrock:{region}:{account}:custom-model/{id}` | `CUSTOM_MODEL` | Account-scoped |
| `*` or `arn:aws:bedrock:*` | `ACCOUNT_REGION_WILDCARD` | Wildcard — `MEDIUM` confidence |
| `arn:aws:bedrock:{region}::foundation-model/*` | `MODEL_WILDCARD` | Provider or family wildcard |

### 6.2 Binding Precedence and Confidence

All bindings produced by static IAM policy scan are capped at `MEDIUM` confidence. `HIGH` is reserved for bindings validated by `iam:SimulatePrincipalPolicy` (CORE-004), which accounts for SCPs, permission boundaries, and explicit denies that static text matching cannot evaluate. This is a deliberate downgrade from the prior model, which assigned `HIGH` to specific-ARN bindings without simulation.

| Condition | `sourceTag` | `confidence` |
|---|---|---|
| Specific model ARN, no condition | `DIRECT_PRINCIPAL_POLICY_BINDING` | `MEDIUM` |
| Specific model ARN, with condition block | `CONDITIONAL_BINDING` | `LOW` |
| Wildcard resource (`*` or `model/*`), no condition | `WILDCARD_ACCOUNT_SCOPE_BINDING` | `MEDIUM` |
| Wildcard resource with condition block | `CONDITIONAL_BINDING` | `LOW` |
| Group-inherited, specific ARN | `GROUP_INHERITED_BINDING` | `MEDIUM` |
| Group-inherited, wildcard | `GROUP_INHERITED_WILDCARD_BINDING` | `MEDIUM` |
| Any binding, simulation-validated (CORE-004) | any | `HIGH` |

Conditional bindings are downgraded to `LOW` because condition evaluation requires runtime context (request tags, IP ranges, time of day) that the inventory cannot supply. A conditional `Allow` is not a reliable access grant without knowing whether the condition would be satisfied.

### 6.3 Deduplication Key

Bindings are deduplicated on the tuple `(principalArn, modelArn, wildcard, conditionJson, bindingOrigin, sourcePrincipalArn)`. `sourcePrincipalArn` is used rather than `sourcePrincipalName` because group names are not unique across accounts; ARNs are. This correctly preserves distinctions between grants inherited from different groups that happen to share a name, and between direct and group-inherited grants to the same model.

### 6.4 Binding ID

Each binding gets a deterministic ID computed as a SHA-256 prefix:

```
mb-{sha256[:16]}  where input = f"{principalArn}|{scopeType}|{scopeResourceName}|{conditionJson or ''}"
```

The `mb-` prefix distinguishes model bindings from agent identity bindings (`ib-` prefix) and tool credential records (`tc-` prefix).

---

## 7. Tool Credential Normalization

### 7.1 Action Group Executor Types

A Bedrock agent action group specifies one of three executor types. The inventory classifies each and extracts the credential or authentication surface accordingly:

| Executor Type | API Field | `credentialType` | `credentialRef` |
|---|---|---|---|
| AWS Lambda | `actionGroupExecutor.lambda` (ARN) | `LAMBDA_EXECUTION_ROLE` | Lambda function ARN |
| Amazon S3 (OpenAPI schema source) | `apiSchema.s3` present | `S3_READ` | S3 bucket ARN |
| Return Control (no executor) | `actionGroupExecutor.customControl = RETURN_CONTROL` | `NONE` | `null` |
| Confluence (knowledge base connector) | `actionGroupExecutor.lambda` + `confluenceConfiguration` present | `CONFLUENCE_SECRET` | Secrets Manager secret ARN |

### 7.2 Lambda Executor — Authentication Surface

When the executor is a Lambda function, the Bedrock agent invokes the Lambda using the agent's own service role (the IAM role configured on the agent as `agentResourceRoleArn`). The Lambda function itself may require additional permissions beyond its resource policy — these are not enumerated by this inventory (that would require policy simulation). The `credentialRef` is the Lambda function ARN; the `credentialType` is `LAMBDA_EXECUTION_ROLE` to signal that the authentication boundary is the agent's service role, not a stored credential.

### 7.3 Credential Record Schema

Each normalized tool credential record contains:

| Field | Type | Description |
|---|---|---|
| `id` | string | `tc-{sha256[:16]}` of `agentId\|actionGroupId` |
| `agentId` | string | Bedrock agent ID |
| `agentArn` | string | Full agent ARN |
| `agentServiceRoleArn` | string | IAM role ARN the agent assumes when invoking this action group (`agentResourceRoleArn` from the agent record) |
| `actionGroupId` | string | Action group ID |
| `actionGroupName` | string | Human-readable name |
| `actionGroupState` | string | `ENABLED` or `DISABLED` |
| `credentialType` | string | `LAMBDA_EXECUTION_ROLE` \| `S3_READ` \| `CONFLUENCE_SECRET` \| `NONE` |
| `credentialRef` | string | ARN or `null` — never the credential value |
| `apiSchemaSource` | string | `S3` or `INLINE` or `null` |
| `functionSchema` | boolean | `true` when using function-definition schema (not OpenAPI) |
| `accountId` | string | AWS account ID |
| `region` | string | AWS region |

The credential value is never included. For `CONFLUENCE_SECRET`, only the Secrets Manager ARN is recorded. For `LAMBDA_EXECUTION_ROLE`, the function ARN is in `credentialRef` and the agent's IAM execution boundary is in `agentServiceRoleArn` — both are required to reason about what the action group can do.

---

## 8. Output Schema

### 8.1 Storage Layout

```
s3://<BUCKET>/bedrock-core-inventory/runs/<TIMESTAMP>/
    models.json
    model-bindings.json
    agent-tool-credentials.json
    principals.json
    manifest.json

s3://<BUCKET>/bedrock-core-inventory/latest/
    (same five files — promoted after run prefix fully written)
```

The run-specific prefix provides an immutable audit trail. `latest/` is the stable read path for downstream connectors. `latest/` is never partially written — the promotion step runs only after all five run artifacts succeed.

### 8.2 `models.json`

Array of foundation model objects from `bedrock:ListFoundationModels`. One entry per model returned by the API, regardless of whether any principal has a binding to it.

| Field | Nullable | Notes |
|---|---|---|
| `id` | No | `modelId` from API |
| `modelArn` | No | Full model ARN |
| `modelName` | No | Human-readable name |
| `providerName` | No | e.g. Anthropic, Amazon |
| `inputModalities` | No | Array: `TEXT`, `IMAGE`, `EMBEDDING` |
| `outputModalities` | No | Array |
| `responseStreamingSupported` | No | Boolean |
| `inferenceTypesSupported` | No | Array: `ON_DEMAND`, `PROVISIONED` |
| `customizationsSupported` | Yes | Array or `null` |
| `accountId` | No | Owning account |
| `region` | No | AWS region |

### 8.3 `model-bindings.json`

Array of normalized identity binding objects — one per qualifying IAM principal per resource ARN (or wildcard scope). Empty when no principals have `InvokeModel`-class permissions.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `mb-{sha256[:16]}` — deterministic, stable across runs |
| `modelArn` | string or null | `null` for wildcard bindings |
| `principalArn` | string | IAM principal ARN |
| `principalType` | string | `ROLE` or `USER` |
| `principalAccountId` | string | AWS account ID |
| `permissions` | string[] | Always `["invoke"]` |
| `scopeType` | string | `MODEL` \| `PROVISIONED_MODEL` \| `CUSTOM_MODEL` \| `ACCOUNT_REGION_WILDCARD` \| `MODEL_WILDCARD` |
| `scopeResourceName` | string | Model ARN or wildcard scope string |
| `sourceTag` | string | `DIRECT_PRINCIPAL_POLICY_BINDING` \| `CONDITIONAL_BINDING` \| `WILDCARD_ACCOUNT_SCOPE_BINDING` \| `GROUP_INHERITED_BINDING` \| `GROUP_INHERITED_WILDCARD_BINDING` |
| `confidence` | string | `HIGH` (simulation-validated), `MEDIUM` (static scan, specific ARN or wildcard), or `LOW` (conditional — condition unevaluated) |
| `wildcard` | boolean | `true` when resource was `*` or a wildcard ARN |
| `conditionJson` | string or null | Serialized IAM condition block |
| `bindingOrigin` | string | `DIRECT_ROLE_POLICY` \| `DIRECT_USER_POLICY` \| `GROUP_INHERITED` |
| `sourcePrincipalType` | string or null | `GROUP` when `bindingOrigin=GROUP_INHERITED` |
| `sourcePrincipalName` | string or null | Group name when inherited |
| `sourcePrincipalArn` | string or null | Group ARN when inherited |

### 8.4 `agent-tool-credentials.json`

Array of normalized tool credential objects — one per action group across all agents. Only action groups with `actionGroupState=ENABLED` are included by default; `DISABLED` groups are included with a `disabled` flag for completeness.

See Section 7.3 for the full field schema.

### 8.5 `principals.json`

Deduplicated set of IAM principals that appear in `model-bindings.json`. One entry per unique `principalArn`. This file lets downstream consumers resolve principal metadata without re-querying IAM.

| Field | Type | Notes |
|---|---|---|
| `principalArn` | string | IAM ARN — primary key |
| `principalType` | string | `ROLE` or `USER` |
| `principalName` | string | Role name or user name |
| `principalAccountId` | string | AWS account ID |
| `bindingCount` | integer | Number of model-bindings referencing this principal |

### 8.6 `manifest.json`

Single object describing the run. Consumed by operational monitoring to verify freshness and completeness.

| Field | Type | Notes |
|---|---|---|
| `generatedAt` | string | UTC ISO-8601 |
| `schemaVersion` | string | Always `1.0` |
| `platform` | string | Always `aws-bedrock-core` |
| `accountId` | string | AWS account ID |
| `region` | string | AWS region scanned |
| `modelCount` | integer | Records in `models.json` |
| `modelBindingCount` | integer | Records in `model-bindings.json` |
| `wildcardBindingCount` | integer | Subset of `modelBindingCount` where `wildcard=true` |
| `conditionalBindingCount` | integer | Subset of `modelBindingCount` where `conditionJson` is non-null |
| `agentToolCredentialCount` | integer | Records in `agent-tool-credentials.json` |
| `principalCount` | integer | Records in `principals.json` |
| `warnings` | string[] | Warning conditions (see §10) |
| `artifacts` | object | File + count per artifact |

---

## 9. Runtime Data Flow

One complete Lambda execution proceeds as follows.

**Step 1 — Configuration.** Account ID resolved from `ACCOUNT_ID` env var or STS `GetCallerIdentity`. Region resolved from `REGION` env var, then `AWS_REGION`, then `us-east-1`. Bucket resolved from `CORE_INVENTORY_BUCKET` env var, default `bedrock-core-inventory`.

**Step 2 — Foundation model collection.** `bedrock:ListFoundationModels` called once. All models returned regardless of principal coverage. Stored in memory as models list.

**Step 3 — IAM model-binding scan.** `scan_roles_for_model_bindings()` and `scan_users_for_model_bindings()` iterate all IAM roles and users respectively. For each principal, inline and attached policies are evaluated. For users, group memberships are enumerated and group policies evaluated with user as principal and group lineage recorded. The action filter is `includes_bedrock_invoke_model()`. Resource parsing handles foundation-model ARNs (empty account segment), provisioned-model ARNs, custom-model ARNs, and wildcards.

**Step 4 — Agent tool credential collection.** `bedrock:ListAgents` called, paginated. For each agent, `bedrock:ListAgentActionGroups` called (`agentVersion=DRAFT`). For each action group, `bedrock:GetAgentActionGroup` called to retrieve executor configuration. Executor type is classified and `credentialType`/`credentialRef` assigned per Section 7.1.

**Step 5 — Normalization.** Model bindings deduplicated per Section 6.3. Binding IDs computed per Section 6.4. `principals.json` derived by deduplicating `principalArn` across all bindings and computing `bindingCount`. Tool credentials normalized per Section 7.3.

**Step 6 — Warning assembly.** Warnings appended to the manifest for: zero model bindings found; one or more wildcard bindings present (`wildcardBindingCount > 0`); one or more conditional bindings present (`conditionalBindingCount > 0`); tool credential collection failed for one or more agents.

**Step 7 — Artifact upload.** All five artifacts written to `runs/{timestamp}/` first. `latest/` promoted only after all five run writes succeed. Upload failure raises `ClientError` and Lambda returns `statusCode 500`. The previous `latest/` is unchanged on failure.

---

## 10. Failure Modes

| Failure | Behavior | Recovery |
|---|---|---|
| `ListFoundationModels` fails | Exception raised; Lambda aborts; returns 500 | Retry on next scheduled invocation |
| IAM `ListRoles` / `ListUsers` fails | Exception raised; Lambda aborts; returns 500 | Retry on next invocation |
| IAM `GetRolePolicy` / `GetPolicyVersion` fails on one policy | WARNING logged; policy skipped; scan continues | Recovered on next run if transient; binding may be missing until resolved |
| `ListAgents` fails | Exception raised; Lambda aborts; returns 500 | Retry on next invocation |
| `ListAgentActionGroups` fails for one agent | WARNING logged; empty credential list for that agent; continues | Recovered on next run if transient |
| `GetAgentActionGroup` fails for one action group | WARNING logged; sparse credential record emitted (`id`, `agentId`, `actionGroupId` only); continues | Recovered on next run if transient |
| S3 `PutObject` fails on any artifact | `ClientError` raised; Lambda returns 500; `latest/` not updated | Previous `latest/` unchanged; retry on next invocation |
| Zero model bindings found | Empty `model-bindings.json` written; manifest warning emitted | Not an error — valid state if no principals have `InvokeModel` permissions |
| Foundation model ARN with empty account segment | Parser handles empty account field; `scopeType=MODEL`; no warning | Not an error — expected for all foundation model ARNs |

---

## 11. Design Decisions

### Why a separate Lambda, not an extension of the agent Lambda

The agent Lambda (`lambda_function.py`) is scoped to `bedrock:InvokeAgent`. Adding model-invocation scanning would require a second IAM action filter, a second resource parser (foundation-model ARNs have a structurally different format from agent and agent-alias ARNs), and a second output artifact. Extending the existing function would couple two independent governance surfaces into one deployment unit, making independent scheduling, failure isolation, and permission scoping impossible. A separate Lambda lets the model-invocation scan run at a different frequency than agent scanning if operational requirements diverge.

### Why a separate S3 bucket

Separation of artifact namespaces prevents a bug in one inventory producer from overwriting or corrupting the output of the other. It also allows independent bucket policies, lifecycle rules, and access controls — the agent connector SA may not need access to the model-binding artifacts, and vice versa.

### Why `bedrock:InvokeInlineAgent` is included in the model action filter

`InvokeInlineAgent` creates an ephemeral agent scoped to a single API call. It invokes a model under the caller's own IAM identity rather than under an agent service role. From a governance perspective, a principal with `InvokeInlineAgent` can effectively invoke any model the inline agent is configured to use — it is equivalent in impact to `InvokeModel` for the purposes of access control inventory.

### Why the agent's service role is not expanded into its constituent permissions

Expanding `agentResourceRoleArn` into full effective permissions (what models the agent can call, what Lambda it can invoke with what permissions) would require IAM policy simulation or recursive policy traversal. This is expensive, requires `iam:SimulatePrincipalPolicy` permissions, and produces results that are only meaningful at the time of simulation. The inventory records the structural configuration (what executor is attached, what credential type) as a stable governance signal. Full effective-access evaluation is a separate concern tracked in the roadmap.

### Why DRAFT agent version is used for action group enumeration

Bedrock agents have DRAFT and numeric versioned states. DRAFT always reflects the current working configuration. Using DRAFT ensures the inventory sees the latest action group configuration before a version is published. Enumerating all published versions would multiply API calls by version count with diminishing governance value — the published versions are snapshots of prior configurations. If version-specific audit is required it can be added as a future enhancement.

### Why `credentialRef` never contains the credential value

For `CONFLUENCE_SECRET`, the Secrets Manager ARN is the governance-relevant fact — it identifies which secret the agent uses, enabling downstream processes to verify rotation status and access controls on that secret. The secret value itself has no governance utility in this context and must never be stored in a plaintext S3 artifact.

### Why `principals.json` is a separate artifact

Embedding principal metadata inline in `model-bindings.json` would repeat the same principal fields on every binding record for a principal with multiple model permissions. `principals.json` normalizes this into a single lookup table, reducing artifact size at scale and simplifying downstream join operations.

---

## 12. Operational Considerations

### Schedule alignment

Recommended Lambda schedule: every 15 minutes to hourly via EventBridge. The model-binding surface changes on the cadence of IAM policy updates — typically slow. The agent tool credential surface changes on the cadence of Bedrock agent configuration updates — also typically slow. A 15-minute schedule provides fresh-enough data for most governance workflows. Sub-15-minute schedules risk IAM API rate limits under large accounts (>5,000 roles).

### IAM API rate limits and retry/backoff

The IAM scan is serial. At 500 roles with 3 attached policies each, approximately 1,500 `GetPolicyVersion` calls are generated per run. IAM `GetPolicyVersion` has a default rate of 5 TPS per account; at this scale the scan takes roughly 5 minutes.

**Retry policy.** All IAM read calls (`GetRolePolicy`, `GetPolicyVersion`, `GetGroupPolicy`, `ListAttachedRolePolicies`, and their user/group equivalents) must be wrapped in a retry loop with exponential backoff on `ThrottlingException` and `RequestExpired`. The implementation must use:

- Initial backoff: 500 ms
- Backoff multiplier: 2×
- Jitter: ±20% of computed delay (full jitter)
- Maximum backoff: 30 s
- Maximum attempts: 5 per call

`boto3`'s built-in retry mode (`standard` or `adaptive`) covers `ThrottlingException` on most IAM calls but not all — `GetRolePolicy` and `GetGroupPolicy` are inline-policy operations that may not be covered. Implement an explicit retry wrapper for these calls rather than relying solely on the SDK retry config.

The list-level calls (`ListRoles`, `ListUsers`, `ListGroupsForUser`) are paginated and abort the Lambda on failure — they are not subject to per-call retry but will benefit from the SDK's standard retry for transient 5xx errors.

For accounts with >2,000 roles, add a `IAM_INTER_CALL_DELAY_MS` environment variable (default `0`) to insert a configurable sleep between calls, reducing sustained throughput and the probability of hitting the burst limit.

### Model binding artifact freshness monitoring

Configure a CloudWatch alarm on the `manifest.json` `generatedAt` field. If the most recent manifest is more than two schedule intervals old, the alarm should fire. The run-specific prefix provides a full audit trail if rollback is needed — the Lambda never deletes historical run artifacts.

### Custom models and provisioned throughput

`bedrock:ListFoundationModels` returns only base foundation models. Custom models (fine-tuned) and provisioned throughput units are separate resource types with different ARN patterns. This inventory records bindings to these ARN patterns (`scopeType=CUSTOM_MODEL` and `PROVISIONED_MODEL`) when they appear in IAM policy resources, but it does not enumerate all custom models or provisioned throughput units — that would require additional API calls (`bedrock:ListCustomModels`, `bedrock:ListProvisionedModelThroughputs`) tracked as future enhancements.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `CORE_INVENTORY_BUCKET` | `bedrock-core-inventory` | S3 bucket for artifact upload |
| `REGION` | `AWS_REGION`, then `us-east-1` | AWS region for all Bedrock and IAM calls. One region per Lambda instance — deploy one instance per region for multi-region coverage. |
| `IAM_INTER_CALL_DELAY_MS` | `0` | Milliseconds to sleep between IAM read calls. Set to 100–200 for accounts with >2,000 roles to reduce throttling risk. |
| `ACCOUNT_ID` | None — STS fallback | If set, used directly; otherwise resolved via `GetCallerIdentity` |

---

## 13. Enhancement Roadmap

| ID | Description | Status |
|---|---|---|
| CORE-001 | Enumerate custom models via `bedrock:ListCustomModels` and include in `models.json` | Backlog |
| CORE-002 | Enumerate provisioned throughput units via `bedrock:ListProvisionedModelThroughputs` and correlate to model-bindings | Backlog |
| CORE-003 | Published agent version enumeration — scan action groups across all published versions, not just DRAFT | Backlog |
| CORE-004 | IAM policy simulation for agent service roles — expand `agentResourceRoleArn` into effective model permissions | Backlog |
| CORE-005 | SCP and permission boundary awareness — flag bindings that may be blocked by organization-level controls | Backlog |
| CORE-006 | Adaptive concurrency for large accounts — parallel IAM scan with bounded worker pool to reduce total scan time while respecting rate limits | Backlog |
| CORE-007 | Correlation artifact — join `model-bindings.json` (who can invoke a model) with agent identity bindings from the agent Lambda (who can invoke an agent) to produce a unified access graph | Backlog |
