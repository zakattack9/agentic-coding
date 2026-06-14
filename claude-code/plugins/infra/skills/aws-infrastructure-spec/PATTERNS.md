# Rendering patterns

Reference patterns for the `aws-infrastructure-spec` skill. These describe *how* to render each kind of resource — not *what* resources to include. The skill's discovery step decides what's in scope; this file decides the shape of each table.

Patterns use placeholders in `{{double-braces}}`. Inline notes start with `{{NOTE: …}}` and must not appear in output.

---

## Top-of-file structure

```
# AWS Infrastructure Specification

Single source of truth for the AWS infrastructure that runs the `{{project_name}}` platform. Every value below reflects the exact configuration provisioned by Terraform under [`infra/terraform/`](../terraform/).

## Table of Contents

1. [{{title}}](#{{slug}})
…
```

The lead paragraph mentions the project (read from `infra/terraform/CLAUDE.md`) and links to `infra/terraform/`. Nothing else. No environment summary. No architecture summary. No history.

---

## Pattern: Overview section

Single env-invariant table; one row per top-level fact. Include rows for:

- AWS regions (primary + any aliased-provider regions)
- Resource naming convention (quote from `infra/terraform/CLAUDE.md`)
- Secret / SSM naming convention if it differs from resource naming
- Terraform `required_version` (from accounts root providers.tf)
- AWS provider `version` constraint
- Reference to the Default Tags section

```
## {{N}}. Overview

| Item | Value |
|---|---|
| AWS regions | `us-west-2` (primary), `us-east-1` (CloudFront / ACM only) |
| Resource naming | `{env}-zilarent-{resource}` (lowercase, dashes) |
| Secret / SSM naming | `zilarent/{env}/{path}` |
| Terraform version | `{{required_version}}` |
| AWS provider version | `{{version_constraint}}` |
| Default resource tags | See [§{{N}}](#{{slug}}) |
```

If a code comment in `providers.tf` or `CLAUDE.md` describes a non-obvious current-state design choice (e.g., why two regions), one short paragraph follows the table.

---

## Pattern: Environments section

Per-env comparison table. Include one row per env-divergent value. Keep it focused on the values that actually differ — do not pad with rows that are identical across envs.

```
## {{N}}. Environments

| Parameter | Production | Staging |
|---|---|---|
| AWS Profile | `{{prod_profile}}` | `{{staging_profile}}` |
| AWS Account ID | `{{prod_account}}` | `{{staging_account}}` |
| VPC CIDR | `{{prod_cidr}}` | `{{staging_cidr}}` |
{{… one row per env-divergent value discovered …}}
```

If a comment justifies a current-state divergence (e.g., "single-instance because the embedded scheduler has no leader election"), one sentence follows the table. Do **not** explain *why the architecture changed* — only why the current values are what they are.

---

## Pattern: VPC / Networking

Render three or four subsections under one section:

- **VPC** — CIDR (per env), DNS support/hostnames, Name tag
- **Subnets** — count, AZs, full CIDR table; followed by a "Subnet usage by workload" table that lists each workload and which subnets it actually uses (read the slicing in `accounts/<env>/main.tf` — e.g., `slice(public_subnet_ids, 0, 2)`)
- **Internet & NAT** — single table covering IGW, NAT(s), EIP(s), route tables, associations
- **VPC Endpoints** — one row per endpoint with type, service, subnets, private DNS

If a comment justifies the set of interface endpoints (e.g., "Secrets Manager and SSM intentionally use NAT egress"), quote it briefly after the endpoints table.

---

## Pattern: Security Groups

Single section, single table. One row per `aws_security_group` discovered. Columns: `Name | Purpose | Inbound Rules | Outbound`.

For inbound, list each ingress rule as `<proto> <port[-range]> from <source>` where source is a CIDR or the name of another SG (use the SG's resource name, not its TF local). For outbound, write `All protocols to 0.0.0.0/0` for unconstrained egress, or describe the constraint, or `—` if no egress is declared (which means default-deny in v5+ provider; flag this only when material).

If a SG that you'd expect to find is provisioned inside a non-security module (e.g., a Redis SG inside the cache module), include it in this table anyway — group by category, not by module.

---

## Pattern: Load Balancing

One section per load balancer. Inside: a single table for the LB itself, then a subsection per listener, then a subsection per target group it points to.

```
## {{N}}. Load Balancer ({{LB type}})

{{NOTE: One sentence stating which module owns the resource, if non-obvious.}}

| Parameter | Value |
|---|---|
| Resource name | `{{name}}` |
| Type | {{Application/Network}} Load Balancer |
| Scheme | {{Internet-facing/Internal}} |
| Subnets | {{which subnets actually passed in}} |
| Security Group | [{{SG name}}](#{{security-groups-anchor}}) |
| Deletion Protection | {{Enabled/Disabled}} |
| Access Logs | {{per-env description if conditional, else single value}} |

### {{Listener N}} (port {{N}})

| Parameter | Value |
|---|---|
| Protocol | {{HTTP/HTTPS/TCP/…}} |
| {{conditional: SSL Policy}} | `{{ssl_policy}}` |
| {{conditional: Certificate}} | ACM certificate from [§{{N}}](#{{certs-anchor}}) |
| Default Action | {{describe}} |

### Target Group (`{{name}}`)

| Parameter | Value |
|---|---|
| Target Type | `{{type}}` |
| Protocol / Port | {{proto}} / {{port}} |
| Deregistration Delay | `{{seconds}}` seconds |
| Health Check Protocol | {{proto}} |
| Health Check Path | `{{path}}` |
| Health Check Interval | `{{seconds}}` seconds |
| Healthy Threshold | `{{n}}` |
| Unhealthy Threshold | `{{n}}` |
| Health Check Timeout | `{{seconds}}` seconds |
| Matcher | `{{matcher}}` |
```

---

## Pattern: Compute (long-running — ASG / EKS / ECS)

One section per ASG. Order: internet-facing first, then workers/back-ends. If env-divergence is heavy, use a per-env table; if not, single-column.

```
## {{N}}. Compute — {{ASG purpose}}

| Parameter | Production | Staging |
|---|---|---|
| ASG name | `{{prod}}` | `{{staging}}` |
| Launch template name | `{{prod}}` | `{{staging}}` |
| Instance type | `{{prod}}` ({{ARM64 | x86_64}}) | `{{staging}}` ({{ARM64 | x86_64}}) |
| AMI source | `image_id = "{{value}}"` | (same / different) |
| Subnets | {{which keys}} | (same) |
| Security group | [{{SG}}](#{{anchor}}) | (same) |
| Instance profile | [`{{name}}`](#{{anchor}}) | (same) |
| Desired / Min / Max | `{{prod n/n/n}}` | `{{staging n/n/n}}` |
| Target group | {{[name](#anchor) or "None — not behind a load balancer"}} | (same) |
| Health check type | {{ELB/EC2}} | (same) |
| Health check grace period | `{{s}}` s | (same) |
| EBS root device | {{device + encryption + delete_on_termination + any size override}} | (same) |
| Launch template version | `{{value}}` | (same) |
| Scaling policies | {{None or list with details}} | (same) |

{{NOTE: Append the CPU architecture to the instance type — Graviton families (t4g/m6g/c7g/r7g/…) or an arm64 base AMI ⇒ (ARM64), else (x86_64). Use the same annotation in the Environments table.}}

{{NOTE: If a comment justifies the sizing (e.g., "single-instance because …"), one sentence follows.}}

### Instance Tags (set by launch template)

| Tag | Value |
|---|---|
{{… every tag_specifications tag …}}

### User Data

{{NOTE: Decode base64encode(...) and quote the script. State if it's conditional on a variable.}}

```bash
{{decoded script}}
```
```

If no user_data is set, omit the subsection. If there are scaling policies, render them as a follow-on table.

---

## Pattern: Compute (serverless — Lambda)

One section per Lambda (or combine when functions are tightly related; the skill's caller decides based on resource count).

```
## {{N}}. {{Lambda purpose}} — Lambda & {{schedule type if any}}

{{NOTE: One-sentence purpose summary derived from the function code or surrounding comments.}}

| Parameter | Value |
|---|---|
| Function name | `{{name}}` |
| Runtime | `{{runtime}}` |
| Handler | `{{handler}}` |
| Timeout | `{{seconds}}` s |
| Memory | `{{MB}}` MB |
| Source | `{{path}}` (zipped via `archive_file`) |
| VPC | {{Yes — subnets/SG / No — reason if a comment justifies}} |
| Tracing | {{X-Ray Active / Off}} |
| CloudWatch log group | `{{path}}` (retention: `{{days}}` d) |
| Environment variables | `KEY=value`, `KEY=value`, … |
| IAM role | `{{role_name}}` |
| Managed policies attached | {{list policy short names}} |
| Inline policy SIDs | {{each SID with one-line scope summary, comma-separated; render full SID detail in the IAM section if scope warrants}} |
| Schedule | `{{schedule name}}`, `group_name = "{{n}}"`, `flexible_time_window { mode = "{{m}}" }`, expression `{{expr}}` |
| Schedule invoke role | `{{role}}` with inline `{{sid}}` (`{{actions}}` on the function ARN) |
```

---

## Pattern: Database

One section per database engine kind (e.g., RDS, DynamoDB, DocumentDB). Per-env table.

Include every argument explicitly set in `aws_db_instance` (or equivalent). For arguments that are *not* set but use important engine defaults (e.g., `port`), include the row with the value derived plus the annotation `(engine default — not set explicitly)`.

```
## {{N}}. Database — {{engine}}

| Parameter | Production | Staging |
|---|---|---|
| Instance identifier | `{{prod}}` | `{{staging}}` |
| Engine | {{engine}} | (same) |
| Engine version | `{{prod}}` | `{{staging}}` |
| Instance class | `{{prod}}` | `{{staging}}` |
| Allocated storage | `{{prod}}` GB | `{{staging}}` GB |
| Storage type | `{{type}}` | (same) |
| Storage encrypted | Enabled | Enabled |
| Multi-AZ | {{prod}} | {{staging}} |
| Port | {{value}} {{(engine default — not set explicitly) if applicable}} | (same) |
| Publicly accessible | No | No |
| Subnet group | `{{name}}` ({{which subnets}}) | (same / different) |
| Security group | [{{SG}}](#{{anchor}}) | (same) |
| Backup retention | `{{days}}` days | (same) |
| Deletion protection | Enabled | Enabled |
| `lifecycle.prevent_destroy` | `{{value}}` | (same) |
| Final snapshot on destroy | {{describe with identifier}} | (same) |
| Copy tags to snapshot | {{Yes/No}} | (same) |
| Master username | `{{name}}` | (same) |
| Master password | {{describe — typically AWS-managed; cross-link to Secrets}} | (same) |
| Database name | {{set value or "Not provided to engine — created out-of-band"}} | (same) |
| Parameter group | {{custom name or "AWS engine default (no custom group)"}} | (same) |
```

---

## Pattern: Cache

Same shape as Database (per-env table). Note the parameter group explicitly — when it's custom, name it and describe family + any overridden settings.

If the AUTH token (or equivalent secret) is sourced via a `data "aws_ssm_parameter"` lookup, describe the source path and add one sentence noting the parameter is operator-owned out-of-band (also list it in the Configuration section).

---

## Pattern: Storage — S3 buckets

One subsection per bucket within the Storage section.

```
### {{N}}.{{m}} {{Purpose}} Bucket — `{{bucket name}}`

| Parameter | Value |
|---|---|
| `force_destroy` | `{{value}}` |
| `lifecycle.prevent_destroy` | `{{value}}` |
| Versioning | {{Enabled/Disabled}} |
| Encryption | {{algorithm}} |
| Public Access Block | {{All 4 settings enabled / partial — list flags}} |
| Lifecycle: {{rule name}} | {{description}} |
| Bucket policy | {{describe — flag which module DEFINES the policy if it's not the same as the bucket-creating module}} |
| Access logs target | {{bucket name or "Disabled" + per-env note if conditional}} |
```

If a comment in code justifies a non-obvious choice (e.g., "Versioning intentionally off on log buckets — no rollback story for log objects"), include and attribute it.

---

## Pattern: CDN — CloudFront

```
## {{N}}. CDN — CloudFront

{{NOTE: One-sentence intro: distribution serves which origin via what access mechanism.}}

| Parameter | Value |
|---|---|
| Origin | `{{domain}}` |
| Origin ID | `{{id}}` |
| Origin Access | {{describe OAC/OAI: name, signing protocol, signing behavior}} |
| `enabled` | `{{value}}` |
| IPv6 | {{Enabled/Disabled}} |
| Price Class | `{{class}}` |
| Aliases | {{describe — tfvar name, current state, what it gates}} |
| Geo restriction | {{None or describe}} |
| Viewer protocol policy | `{{policy}}` |
| Allowed methods | {{list}} |
| Cached methods | {{list}} |
| Compress | {{Enabled/Disabled}} |
| Cache policy | {{Managed name (UUID) or custom}} |
| Origin request policy | {{Managed name (UUID) or custom}} |
| Distribution access logs | {{describe — per-env if conditional}} |

### Viewer Certificate

{{IF conditional on aliases}}
When `{{tfvar}}` is **empty** (current state in {{which envs}}): uses default `*.cloudfront.net` certificate; no ACM cert is provisioned.

When `{{tfvar}}` is **non-empty**:

| Parameter | Value |
|---|---|
| Certificate | ACM cert provisioned in `us-east-1` (defined inside {{module}}) |
| SSL Support Method | `{{method}}` |
| Minimum Protocol Version | `{{version}}` |
{{END}}
```

---

## Pattern: Queue / Messaging / Email / DNS / WAF / etc.

For any category not detailed above, follow the same shape:

1. One section per logical resource family (e.g., one WAF Web ACL = one section).
2. Single env-invariant table for the resource's parameters when there's no per-env divergence; per-env table when there is.
3. A subsection per repeated child resource (e.g., one row per WAF rule, one per SES domain identity).
4. Quote `lifecycle` blocks when present.

If the category is empty (no resources), omit the section entirely.

---

## Pattern: IAM (workload)

```
## {{N}}. IAM — {{role family}} Roles

{{NOTE: One paragraph: how many roles in this family, what managed policies they all attach, which share inline policies, what the trust principal is.}}

| Role | Instance profile | Used by |
|---|---|---|
| `{{role}}` | `{{profile}}` | [{{consumer section}}](#{{anchor}}) |

### Shared Inline Policy SIDs

{{NOTE: Render once when multiple roles share the policy; render once per distinct policy otherwise.}}

| SID | Actions | Resources |
|---|---|---|
| `{{sid}}` | {{actions}} | {{resources}} |
| `{{sid}}` *(dynamic — only when `{{var}}` is non-empty)* | {{actions}} | {{resources}} |
```

---

## Pattern: CI/CD — Federated identity (OIDC + IAM)

```
## {{N}}. CI/CD — {{IdP}} OIDC

| Resource | Value |
|---|---|
| OIDC Provider URL | `{{url}}` |
| Audience | `{{audience}}` |
| Thumbprints | {{list}} |
| {{IdP-identifier rows — e.g., GitHub Org / Repo}} | `{{values}}` |

{{NOTE: One sentence: how many roles in this section, what each is for.}}

### {{N}}.1 {{role purpose}} — `{{role name}}`

#### Trust Policy

{{NOTE: Describe the federated principal, the audience condition, the subject-claim list with whether StringEquals or StringLike. List every subject the trust allows.}}

#### {{inline | customer-managed | both}} Policies

{{NOTE: Render one table per policy resource discovered. Note whether each policy is inline (`aws_iam_role_policy`) or customer-managed (`aws_iam_policy` + attachment). For each SID:}}

| SID | Actions | Resources |
|---|---|---|

{{NOTE: If a single policy is split across multiple `aws_iam_policy` resources (commonly due to size limits), render one table per resource with a clear heading naming the policy.}}

#### AWS-Managed Policy Attachments

{{IF any aws_iam_role_policy_attachment.X point at an AWS-managed policy}}
- `{{managed policy ARN}}`
{{END}}
```

Repeat the role subsection for every OIDC-trusted role.

---

## Pattern: Configuration — SSM Parameter Store

```
## {{N}}. SSM Parameter Store

All under the `/zilarent/` namespace.

| Path | Type | Value | Owner |
|---|---|---|---|
{{… one row per aws_ssm_parameter resource discovered, including dynamic `for_each` defaults …}}
{{… one row per `data "aws_ssm_parameter"` lookup, flagged `Operator (out-of-band)` …}}
```

**Inclusion rule for SSM rows:**
- Include parameters created by `aws_ssm_parameter` resources (literal or `for_each`).
- Include parameters read by `data "aws_ssm_parameter"` lookups — these are operator-owned out-of-band parameters; flag the Owner as such.
- **Exclude** anything that appears only in commented-out tfvars examples.
- For `for_each` defaults from `accounts/<env>/variables.tf`, one row per default key.

---

## Pattern: Secrets — Secrets Manager

```
## {{N}}. Secrets Manager

{{NOTE: One paragraph: which module owns secrets, the lifecycle posture (prevent_destroy on secret, ignore_changes on version), the for_each shape.}}

| Secret Path | Contents | Created By | Populated By |
|---|---|---|---|
{{… one row per logical secret …}}
```

For consolidated secrets with a documented JSON shape (in a tfvars comment), quote the JSON-key list. For per-tenant secrets, describe the pattern, not specific tenants (tenants come and go).

---

## Pattern: Observability — CloudWatch

```
## {{N}}. Observability — CloudWatch Logs

{{NOTE: Which module creates the log groups; what variable controls the set.}}

| Log Group | Retention | Tailed by |
|---|---|---|
{{… one row per aws_cloudwatch_log_group …}}
```

If alarms / metric filters / dashboards exist, follow with one subsection each. If none exist, just the table.

---

## Pattern: Env-specific extras

When an env has resources defined in its account root that don't exist in other envs (e.g., `accounts/prod/logging.tf`), render them as a top-level section titled by the env and what the extras are:

```
## {{N}}. {{Env-specific theme}} ({{env}} only)

Provisioned **only** in `accounts/{{env}}/{{file}}.tf` — other envs omit the corresponding wiring.

### {{N}}.{{m}} {{Resource group}}

| {{Resource}} | {{detail column}} |
|---|---|
{{… one row per resource …}}
```

When the file contains inline comments justifying choices (e.g., "Versioning intentionally OFF on log buckets — no rollback story for log objects; noncurrent storage adds cost without benefit"), quote the comment briefly. This is current-state design rationale, not history — keep it.

---

## Pattern: Application Catalog — AppRegistry / equivalent

```
## {{N}}. Application Manager — AppRegistry

{{NOTE: Which module provisions; how many resources.}}

| Resource | Name |
|---|---|
{{… one row per resource …}}

{{NOTE: One paragraph or fenced HCL block quoting the attribute group metadata defaults from the module's variables.tf.}}

{{NOTE: One paragraph on how the application_tag (or equivalent) participates in default_tags.}}
```

---

## Pattern: Default Tags

```
## {{N}}. Default Tags

{{NOTE: Walk accounts/<env>/providers.tf. Render one row per `provider "aws"` block.}}

| Provider | Region | Purpose | `default_tags` |
|---|---|---|---|
| {{alias or "(unaliased)"}} | {{region}} | {{purpose}} | {{tag map summary, including any merge() call}} |

| Tag | Value |
|---|---|
{{… one row per merged tag …}}
```

If `bootstrap/<env>/providers.tf` declares a distinct tag set, mention it in one sentence after the table.

---

## Pattern: State Backend

```
## {{N}}. Terraform State Backend

Provisioned out-of-band by [`infra/terraform/bootstrap/{env}/`](../terraform/bootstrap/).

### S3 State Bucket

| Parameter | Production | Staging |
|---|---|---|
| Bucket name | `{{prod}}` | `{{staging}}` |
| Region | `{{region}}` | `{{region}}` |
| Versioning | {{Enabled/Disabled}} | (same) |
| Encryption | {{algorithm}} | (same) |
| Public Access Block | {{All 4 settings enabled / partial}} | (same) |
| Lifecycle | {{describe}} | (same) |
| `force_destroy` | `{{value}}` | (same) |
| `lifecycle.prevent_destroy` | `{{value}}` | (same) |

### State Keys

| Stack | Bucket | Key |
|---|---|---|
| Bootstrap (`bootstrap/{env}/`) | `{{bucket}}` | `{{key}}` |
| Accounts root (`accounts/{env}/`) | `{{bucket}}` | `{{key}}` |

### Locking

{{NOTE: Read the backend "s3" block in bootstrap/<env>/providers.tf and the resources in main.tf. If `use_lockfile = true` and no DynamoDB table resource, write: "S3-native locking via `use_lockfile = true`. No separate lock table." If a DynamoDB table resource exists, describe it. If neither indicator is present, write what the code shows.}}
```

---

## Pattern: Resource Name Index (appendix)

Always the final section. Walk every previous section and collect every named AWS resource. Group by the section categories you used. One table per group, two columns (`Resource | Name`). Use the project's env placeholder convention (read from `infra/terraform/CLAUDE.md`).

Include resources whose only human-facing identifier is a `Name` **tag** rather than a `name`/`identifier` argument — **ACM certificates are the recurring omission** (`[env]-zilarent-cert`, `[env]-zilarent-cdn-cert`). Group certificates with WAF under the security group heading (e.g., "Networking, Security & Certificates"); the doc has no standalone certificates index group. Every backticked resource name anywhere in the body must have a row here.

**Subsection numbering.** Number the index groups as `{N}.1`, `{N}.2`, … where `{N}` is this section's number (e.g., `### 25.1 Networking & Security`). This matches subsection numbering used elsewhere in the doc (`### 3.1`, `### 19.1`, etc.) and keeps anchors uniform.

Group headings should mirror the section headings (e.g., "Networking & Security", "Compute & Load Balancing", "Data Layer", "Storage & CDN"). Don't invent groupings that don't correspond to actual sections.

---

## Anchor slug rules (recap)

See SKILL.md for the authoritative rules. Quick reference:

- Lowercase, strip punctuation that isn't space/hyphen/underscore, then each whitespace character → `-` (no run-collapsing).
- `## 5. Foo` → `#5-foo`
- `## 6. Compute — Web ASG` → `#6-compute--web-asg` (em-dash strips; surrounding spaces remain as two adjacent hyphens)
- `### 16.1 Bar` → `#161-bar`

If a cross-reference doesn't resolve during self-verification, re-derive its slug from the heading using those rules.
