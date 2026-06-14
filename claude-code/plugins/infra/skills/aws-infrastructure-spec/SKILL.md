---
name: aws-infrastructure-spec
description: Generate or regenerate `infra/docs/aws-infrastructure-spec.md` — the single source-of-truth specification of the AWS infrastructure that runs cars.bdv — purely from the live Terraform code and supporting configs. Use when the user asks to create, regenerate, refresh, sync, or update the AWS infrastructure spec. Safe to run when no spec exists today (produces it from scratch) and after any Terraform change (full rewrite — never patches in place).
disable-model-invocation: true
---

Generate `infra/docs/aws-infrastructure-spec.md` from the live Terraform tree by **discovering** what exists in code today and rendering it. Never patch the existing file. Never describe what *used to* be there. The spec is a snapshot of the current code, nothing more.

The Terraform tree and `infra/` directory layout change frequently — modules get added, removed, renamed, split, merged; architectural patterns shift. This skill must produce a correct, well-organized spec on the first try **regardless of what changed**. To stay flexible:

- **No module names are baked into this skill.** Discover modules at runtime.
- **No section names are prescribed.** Section *categories* are ordered (below); specific section titles come from what's in code.
- **No IAM Sid names, no resource ARNs, no config parameter paths are listed in this skill.** They are all derived from a code walk.
- **No migration history or rationale** appears in the output unless an inline code comment explains a still-current design choice.

## Source-of-truth hierarchy

| Source | Role |
|---|---|
| `infra/terraform/**/*.tf` | **Only source of truth** for resource definitions, names, conditional/dynamic blocks, lifecycle |
| `infra/terraform/accounts/**/*.tf` and `terraform.tfvars` | Per-environment wiring, sizing, tfvars defaults and overrides |
| `infra/terraform/accounts/**/providers.tf` | Terraform version, AWS provider pin, `default_tags`, provider aliases |
| `infra/terraform/bootstrap/**/*.tf` | Terraform state backend |
| `infra/terraform/CLAUDE.md` | Project rules — naming convention, `ignore_changes` carve-outs, what's out of scope for Terraform |
| `infra/terraform/README.md` (if present) | Operator overview |
| `.github/workflows/*.yml` | CI/CD context (which workflows assume which OIDC role; which workflow writes the AMI SSM param) |
| `infra/deploy/`, `infra/ami/`, `infra/systemd/`, `infra/fpm/`, `infra/maintenance/`, `infra/vhosts/` | Support scripts and host configs — read only to interpret a Terraform reference (e.g., what `bootstrap-instance.sh` does) |

**Hard exclusions** — never read, never cite, never let them influence the output:

- `infra/docs/**` — including any existing `aws-infrastructure-spec.md`. Treat the directory as absent for the duration of the skill.
- `infra/specs/**` — initial plans, audit reports, migration notes.
- Any prior Claude transcript, summary, or memory.

If the spec exists, do **not** read it. The hard exclusion forbids reading `infra/docs/**`, but the editor refuses to `Write` over a file it has never seen read — so the only compliant way to do a full overwrite is to **delete the file first** with `Bash` (`rm -f infra/docs/aws-infrastructure-spec.md`) and then `Write` it fresh. Never open it to read or diff. See [Output](#output).

## What "no historical context" means

These belong in commit messages or PR descriptions, not in the spec. Do **not** write any of:

- "The previous X has been retired."
- "Consolidated from N separate Y into one Z."
- "Migrated from A to B."
- "Replaces the legacy …"
- "Used to be in module X, now lives in module Y."
- References to empty module directories that signal a deletion.
- The word "previously" describing a Terraform resource, or any sentence whose tense is past with respect to the live code.

If an inline comment in a `.tf` file explains a **still-current** design choice (e.g., "single-instance because the embedded scheduler has no leader election"), you may quote or paraphrase it briefly — that's a description of the current pattern, not history. Distinguish on this test: does the comment justify what's there now? Keep. Does it explain what changed? Drop.

If you find directories under `infra/terraform/modules/` that contain no `.tf` files (only `.terraform/` or `.build/` artifacts), they do not exist for the purposes of this spec. Do not mention them.

## Methodology

### Step 1 — Discover modules and resources

Run `Glob "infra/terraform/modules/*"` to list module directories. For each one:

- If it has at least one `.tf` file, it's a live module. Read its `main.tf`, `variables.tf`, `outputs.tf`.
- If it has only `.terraform/` / `.build/` artifacts (no `.tf` files), it's not a module. Skip it. Do not mention it anywhere in the output.

Then read every account root and its supporting files (`accounts/<env>/`), every bootstrap stack (`bootstrap/<env>/`), and `infra/terraform/CLAUDE.md`. The account roots are the source of truth for which modules are actually instantiated, which env-divergent values flow in, and which optional features are wired (access logs, flow logs, cross-account ARNs, etc.).

Use parallel `Read` / `Glob` / `Grep` calls aggressively — the walk is fully read-only.

### Step 2 — Classify each live module by AWS resource category

For each module, decide the category it belongs to from the table below by inspecting its `resource` declarations. A module may span multiple categories (e.g., a `data` module that creates both RDS and Secrets Manager resources should be rendered in both the **Data** and **Secrets** sections, with cross-references). When a module straddles categories, render the larger half in its primary category and cross-reference the rest.

| Category (in spec order) | AWS resource types that map here |
|---|---|
| Networking | `aws_vpc`, `aws_subnet`, `aws_internet_gateway`, `aws_nat_gateway`, `aws_eip`, `aws_route_table`, `aws_route_table_association`, `aws_vpc_endpoint`, `aws_flow_log` |
| Security Groups | `aws_security_group`, `aws_security_group_rule`, `aws_vpc_security_group_*_rule` (group these in one section even when defined across multiple modules) |
| Load Balancing | `aws_lb`, `aws_lb_listener`, `aws_lb_listener_rule`, `aws_lb_target_group`, `aws_lb_target_group_attachment` |
| Compute (long-running) | `aws_launch_template`, `aws_autoscaling_group`, `aws_autoscaling_policy`, `aws_autoscaling_schedule`, `aws_instance`, `aws_eks_*`, `aws_ecs_*` |
| Compute (serverless) | `aws_lambda_function`, `aws_lambda_permission`, `aws_lambda_event_source_mapping`, `aws_scheduler_schedule`, `aws_cloudwatch_event_*` |
| Database | `aws_db_instance`, `aws_db_subnet_group`, `aws_db_parameter_group`, `aws_rds_cluster*`, `aws_dynamodb_table` |
| Cache | `aws_elasticache_*`, `aws_memorydb_*` |
| Storage | `aws_s3_bucket`, `aws_s3_bucket_*` |
| Queue / Messaging | `aws_sqs_queue*`, `aws_sns_topic*`, `aws_msk_*`, `aws_mq_*` |
| CDN | `aws_cloudfront_*` |
| DNS | `aws_route53_*` |
| Email | `aws_ses_*` |
| WAF / Shield | `aws_wafv2_*`, `aws_shield_*` |
| Certificates | `aws_acm_certificate*` |
| Identity (workload) | `aws_iam_role`, `aws_iam_role_policy*`, `aws_iam_instance_profile` (when the role is trusted by an AWS service — EC2, Lambda, etc.) |
| Identity (federated / CI/CD) | `aws_iam_openid_connect_provider`, `aws_iam_role` trusted by an external IdP, `aws_iam_policy` attached to such roles |
| Configuration | `aws_ssm_parameter`, `aws_appconfig_*` |
| Secrets | `aws_secretsmanager_secret*`, `aws_kms_*` (when guarding secrets) |
| Observability | `aws_cloudwatch_log_group`, `aws_cloudwatch_metric_alarm`, `aws_cloudwatch_dashboard`, `aws_xray_*` |
| Application Catalog | `aws_servicecatalogappregistry_*`, `aws_serviceregistry_*` |
| State Backend | (in `bootstrap/` only — typically `aws_s3_bucket` for tfstate plus locking primitive) |

If a category has no resources in the entire tree, **do not render a section for it.** A spec with no Queue/Messaging section is correct when no SQS/SNS/etc. exists.

If a new resource type appears that doesn't fit any category above, add a category in the obvious place (e.g., a `aws_eks_cluster` would justify a "Container Orchestration" subsection inside Compute). Document the category in the spec only when the cell is non-empty.

### Step 3 — Determine the canonical section order

Sections appear in the spec in this order. Skip any whose category is empty:

1. **Overview** (provider versions, naming convention, top-level facts; always present)
2. **Environments** (per-env divergence summary; always present if more than one account exists)
3. **Networking**
4. **Security Groups**
5. **Load Balancing** (and any listener/target-group detail)
6. **Compute** (long-running): one section per ASG/EKS/ECS cluster. If there are web + worker ASGs, render them as **separate sections** in this order (whichever is internet-facing first).
7. **Compute** (serverless): one section per Lambda function (or one combined section if functions are tightly related)
8. **Database**
9. **Cache**
10. **Storage**
11. **Queue / Messaging**
12. **CDN**
13. **DNS**
14. **Email**
15. **WAF / Shield**
16. **Certificates** (and how they attach — to listeners, to CDN)
17. **Identity (workload)**: one section per role family (typically web/worker/etc.)
18. **Configuration** (SSM Parameter Store, etc.)
19. **Secrets** (Secrets Manager, etc.)
20. **CI/CD — Identity (federated)** (OIDC provider + roles)
21. **Observability**
22. **Env-specific extras** — resources defined in env-only account files (e.g., `accounts/prod/logging.tf`). Includes the *support* resources (log groups, IAM roles, buckets) that wire optional features of shared modules. When a shared-module resource is gated on env-specific support (e.g., `aws_flow_log` in `modules/network` only created when an env-specific log-group ARN is passed), document the resource in its primary category section (here, Networking) and document the env-specific support in this section, with cross-links both ways.
23. **Application Catalog** (AppRegistry, etc.)
24. **Default Tags** (provider blocks + tag map)
25. **State Backend**
26. **Resource Name Index** (appendix)

Number sections sequentially in the order they actually appear (1, 2, 3, …). The numbers above are *category order*, not literal section numbers — drop categories that don't apply and renumber.

### Step 4 — Render each section

Open `PATTERNS.md` (alongside this SKILL.md) and apply the appropriate rendering pattern. Patterns are organized by resource category. Each pattern specifies which fields to render and in what table layout.

Section anchors follow GitHub-Flavored Markdown rules. The accurate model:

1. Lowercase the heading text.
2. Strip every character that isn't a letter, digit, space, hyphen, or underscore. (Em-dashes, periods, parentheses, slashes, ampersands, etc. all strip.)
3. Replace **each whitespace character** with a single hyphen. **Do not collapse runs.** Two adjacent spaces become two adjacent hyphens.

Examples (verify yours render the same in GFM):

- `## 5. Load Balancer (ALB)` → `#5-load-balancer-alb` (period and parens strip; single spaces become single hyphens)
- `## 6. Compute — Web ASG` → `#6-compute--web-asg` (em-dash strips; the two spaces surrounding it remain and each become a hyphen → `--`)
- `### 16.1 Foo & Bar` → `#161-foo--bar` (period strips; `&` strips; two adjacent spaces → `--`)
- `### 16.1 Foo` → `#161-foo`

The TOC at top must list every section in order; every link must resolve. After rendering, walk every `[label](#anchor)` in the body and confirm it matches a heading you wrote. When a label names a specific section number (`§7`, `§19.1`, `§3.5`), point it at *that* section/subsection's anchor — not the parent. A `§3.5` reference must target `#35-vpc-flow-logs`, not `#3-networking`; both resolve, but only one matches the label (see self-verification item 4a).

### Step 5 — Render the Resource Name Index

Walk every section you just rendered. Collect every named AWS resource (resource names, instance profile names, Lambda names, log group names, SG names, etc.). Group them under section-category headings and render a two-column table per group (`Resource | Name`). The grouping must mirror your section structure — don't invent new categories here.

Do **not** overlook resources whose only human-facing identifier is a `Name` **tag** rather than a `name`/`identifier` argument — **ACM certificates are the recurring miss** (their tag is `[env]-zilarent-cert` / the CDN cert's `[env]-zilarent-cdn-cert`). Every backticked resource name that appears anywhere in the body must have a row here; certificates belong in the same group as WAF (a Networking/Security/Certificates group), since the doc has no standalone certificates index group.

### Step 6 — Self-verify

Run the [Self-verification checklist](#self-verification-checklist) before declaring done. Fix any failure, re-verify. Don't ask the user.

## Authoring rules

1. **Env placeholder.** Read `infra/terraform/CLAUDE.md` for the placeholder convention the project uses (e.g., `[env]`, `[environment]`, `<env>`) and reuse it consistently for resource names + paths. Don't invent your own placeholder. Per-env tables resolve the placeholder.
2. **One table per parameter cluster.** Per-env divergence → two-column table (`Production | Staging`). Env-invariant → single-column table.
3. **Quote exact values from code.** Strings get backticks. For parameters whose names are nouns (Versioning, Encryption, Multi-AZ), prefer `Enabled` / `Disabled` over raw `true` / `false`.
4. **Cross-link every section reference.** When section A mentions a resource defined in section B, link to B.
5. **Dynamic / conditional resources** — when a `resource` has `count = … ? 1 : 0` or a Sid sits inside a `dynamic { for_each = … }` whose iterator is conditional, annotate inline: `*(only when {var} is non-empty)*` (or whatever the gating condition actually is). Don't omit the resource — its conditional nature is information.
6. **Inline comments.** If a `.tf` comment justifies a non-obvious current value (e.g., "encryption at rest with KMS would add complexity; SSE-S3 covers compliance"), you may quote it briefly. If the comment is migration history ("we used to use KMS, switched to SSE-S3"), drop it — describe only the current state.
7. **IAM policy SIDs.** For each SID, render `| {SID} | {actions} | {resources} |`. **Enumerate every action verbatim** — even if the list is 20+ entries long. Do not collapse into `"N actions"` summaries or category glosses; this spec is a source-of-truth doc and partial action lists make it impossible to audit granted permissions. The `actions` cell may wrap across many lines; that's fine. Same rule for `resources`: list every ARN pattern, even if the list is long. Annotate `*(dynamic — only when …)*` when applicable. Annotate `(prod-only)` etc. when the SID only renders in one env.
8. **Lambda env vars / config maps.** Render as `KEY=value` comma-separated, in declaration order.
9. **Cross-module ownership.** When module A defines a resource that conceptually belongs to module B's section (e.g., a bucket policy defined in the CDN module but attaching to the storage module's bucket), say so in one sentence — that's a real fact about the code organization, not history.
10. **Empty tfvar state.** When a tfvar is `[]` or `{}` today but the wiring is in place, render the wired behavior and add one short sentence: "Currently `[]` in both envs." Don't expand to multi-paragraph explanations.

## Resource-kind-specific rendering hints

These supplement the patterns in `PATTERNS.md`. Apply only when the relevant resource exists:

- **Launch templates** — decode `base64encode(...)` user data and quote the script in a fenced block. Note whether user_data is conditional. List every `tag_specifications` block.
- **ASGs** — Quote `health_check_type`, `health_check_grace_period`, the subnets actually passed in (often `slice(var.private_subnet_ids, 0, 2)` rather than all four), whether the ASG attaches to a target group, every scaling policy or scheduled action attached. If none exist, write "Scaling policies: None" — don't omit the row. Annotate the instance type with its CPU architecture when derivable: Graviton families (`t4g`, `m6g`, `c7g`, `r7g`, …) or an `arm64` base AMI ⇒ `(ARM64)`; otherwise `(x86_64)`. Architecture is a real current-state attribute (AMI/runtime compatibility depends on it) — carry the same annotation into the Environments table's instance-type rows.
- **Target groups** — render every health check field in one table.
- **ALB / listeners** — quote `ssl_policy` verbatim; for the HTTP-to-HTTPS redirect, quote the exact `status_code`.
- **RDS** — render every `aws_db_instance` argument explicitly set in code. Note when an argument is *not* set (e.g., "port not set — engine default 3306"). Note `manage_master_user_password = true` and cross-link to the Secrets Manager section for the master secret. Note any parameter group reference (or its absence).
- **ElastiCache** — render `parameter_group_name`. If it's a custom group, describe its family and any non-default settings.
- **S3** — render `force_destroy`, `lifecycle.prevent_destroy`, versioning state, encryption algorithm, public-access-block (note all four flags), every `aws_s3_bucket_lifecycle_configuration` rule. For bucket policies, note which module *defines* the policy if it's not the same as the bucket-creating module.
- **CloudFront** — render the cache and origin-request policy IDs (UUIDs) verbatim. Render viewer-cert logic as a "when aliases empty / when aliases set" pair.
- **Lambda** — render runtime, handler, timeout, memory, source dir, VPC config (yes/no with reason if a comment justifies), tracing mode, log group + retention, env vars, IAM role + managed-policy attachments + every inline SID with full actions/resources. Render the schedule (if any) on the same Lambda with `group_name`, `flexible_time_window`, and `schedule_expression`.
- **WAF** — render the default action, every rule's priority/name/statement-type/action, and the IP set's lifecycle.
- **ACM** — for the regional cert, render `validation_method` and the full lifecycle block. For any CloudFront-bound cert, note the conditional logic (typically `count = length(var.aliases) > 0 ? 1 : 0`), the `us-east-1` provider alias used, and the same lifecycle.
- **IAM (workload)** — for each role: trust principal, attached managed policies, every inline policy SID. If two roles share an identical inline policy (e.g., web + worker), say so once and don't duplicate the SID table.
- **IAM (federated)** — render the OIDC provider URL, audience, thumbprints. For each role: full trust block (federated principal, audience condition, subject-claim list with whether it's `StringEquals` or `StringLike`). For each customer-managed policy attached to the role, render its full SID table. For each AWS-managed policy attachment, list the ARN.
- **SSM Parameter Store** — list every `aws_ssm_parameter` created. Also list every parameter accessed via `data "aws_ssm_parameter"` and flag those as **operator-owned out-of-band** (not Terraform-managed). Do not list parameters that only appear in commented-out tfvars examples.
- **Secrets Manager** — for each `aws_secretsmanager_secret` with `for_each`, render the path template and the lifecycle (typically `prevent_destroy = true` on the secret and `ignore_changes = [secret_string]` on the version). If a placeholder JSON shape is documented in a tfvars comment, quote the comment block.
- **Default tags** — list every `provider "aws"` block in account roots: alias (or "unaliased"), region, profile, and the literal `default_tags` map (including any `merge(...)` calls).
- **State backend** — describe what `bootstrap/<env>/main.tf` actually creates. Determine locking by what's in the backend block + what resources exist: if `use_lockfile = true` is in `terraform { backend "s3" { … } }` and there is NO `aws_dynamodb_table` resource, locking is S3-native — say so. If a DynamoDB table resource exists, describe it. Don't infer either way without checking.

## Self-verification checklist

After writing the file, verify each item. Re-read the relevant code; do not trust your own earlier extraction.

1. **Every live module is represented.** For each directory in `infra/terraform/modules/` that has `.tf` files: confirm at least one section of the spec describes its resources. If not, add one.
2. **No dead-module references.** Search the rendered spec for any module name. Every module name mentioned must correspond to a directory that contains live `.tf` files.
3. **No historical narrative.** Search the rendered spec for any of: `previous`, `previously`, `retired`, `removed`, `migrated`, `replaced the`, `legacy`, `used to`, `formerly`, `consolidated from`, `now lives in` (when used to contrast with where it lived before). Any hit is a violation — rewrite the sentence to describe only the current state.
4. **TOC anchors resolve.** Every `[…](#anchor)` link in the body must match a heading that exists in the file.
4a. **Numbered labels match their target.** When a link's visible label carries a section number — `[§9](…)`, `[§19.1](…)`, `(see [§3.5](…))` — the target anchor must be **that exact section/subsection's** anchor, not merely *some* heading that resolves. A link labeled `§3.5` that points at `#3-networking` (the parent) is a defect even though it resolves: it passes item 4 but misleads the reader. This is the failure mode renumbering introduces — after you renumber sections, re-derive every numbered cross-reference's anchor from the heading it actually names, and confirm the label's number equals the leading number of the target anchor (`§3.5` ⇒ `#35-…`, `§19.1` ⇒ `#191-…`).
5. **Per-env spot checks.** Pick three env-divergent parameters from `accounts/{prod,staging}/variables.tf` (e.g., a sizing var, an instance class, a CIDR) — verify the rendered values match the defaults exactly.
6. **Conditional resources annotated.** For every `resource` with `count = … ? 1 : 0` and every IAM Sid inside a `dynamic { for_each = var.X != "" ? [1] : [] }`: confirm the rendered entry has an inline conditional annotation.
7. **No exclusions read.** No content from `infra/docs/**` or `infra/specs/**` informed the output. (You shouldn't have read those files — re-confirm by re-checking your tool call log mentally.)
8. **Resource Name Index parity.** Every named resource that appears in a section's body must appear in the Index — including ACM certificates and anything named only by a `Name` tag (the easiest rows to drop). Spot-check 5 randomly chosen names, and explicitly confirm the Certificates section's cert names are present in the Index.
9. **Empty module-dir invisibility.** Search the rendered spec for the names of any empty directories under `modules/`. Zero hits is required.
10. **CI/CD policy counts.** If the codebase has a federated role with split customer-managed policies, count the policy resources in code and confirm the spec lists exactly that many. Don't hardcode the count from memory.
11. **IAM action lists are complete.** For each SID rendered in any IAM/OIDC section, spot-check 2 SIDs and verify every action listed in code is in the table cell. No `"N actions"` count summaries are allowed — those fail the check.
12. **Resource Name Index groups are numbered.** Each index group uses `### {N}.{m} {Group}` format (e.g., `### 25.1 Networking & Security`).

## Output

Write the spec to `infra/docs/aws-infrastructure-spec.md` as a **full overwrite**. Because you must not `Read` anything under `infra/docs/**` and the editor will not let you `Write` over an unread existing file, the compliant sequence is:

1. `Bash`: `rm -f infra/docs/aws-infrastructure-spec.md` (removes the old file without reading it; no-op if it doesn't exist).
2. `Write`: create the file fresh.

The file must begin with the H1 title, a one-line lead, the TOC, then sections in canonical order, ending with the Resource Name Index.

Do not print the spec to chat. Reply with a single sentence summarizing what was written.

## Rules

- **Don't read `infra/docs/**` or `infra/specs/**`.**
- **Don't make AWS API calls.** Read-only against the local file tree.
- **Don't run `terraform plan` / `apply`.**
- **Don't ask the user.** Every decision must come from the code.
- **Don't include design rationale or migration history.** Describe what exists, period.
- **Don't carry assumptions from this skill's last run.** Re-discover every time.
