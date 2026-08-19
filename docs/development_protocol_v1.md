# MarketVault Development Protocol v1

MarketVault 工程流程的架构 / roadmap 文档。本文档说明 Development Protocol
v1（DP1）的动机，记录优化前的旧流程观测值，并定义后续 PR 实现的方向。

- 策略文档：[DEVELOPMENT_PLAYBOOK.md](governance/DEVELOPMENT_PLAYBOOK.md) 与
  [RELEASE_PLAYBOOK.md](governance/RELEASE_PLAYBOOK.md)。
- Agent 执行契约：[AGENT_HANDOFF.md](governance/AGENT_HANDOFF.md)。

## 1. 状态

DP1 是 v0.7.0 正式发布并完成真实使用练习之后的首个流程工程任务。DP1 只
定义策略：

- 不修改产品代码、版本、依赖、public API、CLI、schema 或 artifact format。
- 尚不优化 CI 或测试；后续 PR 实现本文档定义的策略。
- 不以任何方式改动已密封的 v0.7.0 release。

## 2. 动机与旧流程观测（Legacy Workflow Observation）

触发 DP1 的案例是 v0.7.0 lifecycle PR（`docs: record v0.7.0 formal
release state`，PR #54）——观测到的 lifecycle/docs workflow 案例，即实际
测量的流程 benchmark（process benchmark）。真正的 v0.7.0 real-usage
exercise 是随后一次独立活动，不是同一个测量。记录到的旧流程观测值：

- PR #54 lifecycle/docs workflow ≈ 63 min（wall-clock）。
- 本地测试主导 wall-clock 时间。
- 单个受影响的 regression 测试文件就可能需要数分钟。
- 该 PR 生命周期内本地重复执行了多次完整套件。
- GitHub CI 目前执行多个完整套件环境（Python 3.11 与 3.14 矩阵、PyArrow
  24 可移植性 gate，各自运行完整离线套件）。
- package / release 验证还额外增加一个 CI 阶段（package build、
  fresh-wheel smoke、SHA256 closure）。

### 63 分钟数字的含义边界

PR #54 的约 63 分钟是优化前的历史观测值（优化前参考值，
Pre-optimization Reference），不是 Development Protocol v1 的性能
baseline / target baseline / acceptable baseline。

该数字仅用于：

- 记录旧流程的实际耗时；
- 衡量未来优化带来的改善幅度；
- 提供 before/after comparison。

该数字绝不表示：

- 可接受性能（acceptable performance）；
- Development Protocol v1 的目标耗时；
- correctness gate；
- performance acceptance threshold。

不断言精确百分比：记录的是单个 lifecycle PR 的 wall-clock 观测，不是计时
研究。问题在性质上很清楚——小变更反复付出完整套件级验证的代价——但 DP1
刻意不声称观测不支持的具体占比。

## 3. 核心原则：FASTER, SAME SAFETY

更快，但保持同等安全等级。

DP1 的目标是在保留当前所有安全保证的同时，减少反复出现的人类 / agent
指令开销与 wall-clock 延迟。

安全不为速度让步。今天存在的每个 gate 都继续存在：

- scope freeze
- exact base
- final-head CI
- merge gate
- main verification
- release gate
- artifact hash closure

DP1 的策略减少的是重复验证（同一变更反复跑本地完整套件）与重复指令
（每次 prompt 重复完整 gate 规范），而不是 gate 本身。

## 4. Development Protocol v1 的六个方向

后续 PR 实现这些方向。DP1 不实现它们；只定义与排序。

### 4.1 分层本地测试（Layered Local Testing）

三个本地验证层级——LEVEL 1 focused development、LEVEL 2 submission
readiness、LEVEL 3 authoritative full verification——让小编辑只跑它需要的
验证，完整套件的权威落在 final-head CI。策略见
[DEVELOPMENT_PLAYBOOK.md](governance/DEVELOPMENT_PLAYBOOK.md) 第 2 节。

### 4.2 并行测试（Parallel Testing）

affected regression surface 与完整套件可以在本地以并行 pytest 进程运行，
使 regression surface 的 wall-clock 代价不再随运行时间线性增长。

### 4.3 自动化 PR audit（Automated PR Audit）

**状态：DP2 implemented**。实现为 [scripts/audit_pr.py](../scripts/audit_pr.py)
（read-only、确定性、无 GitHub / network 访问；测试见
[tests/test_audit_pr.py](../tests/test_audit_pr.py)）。CI 集成是后续独立任务，
不在 DP2 范围内。

脚本化的 PR audit，机械地检查冻结范围契约（changed-file list 与 scope
一致、无 product / version / dependency / API / CLI / schema / workflow
变更），无需人类或 agent 重读整个 diff。audit 是审查的机械部分；
independent review 仍由人类或独立审查者判断。

### 4.4 仓库原生 playbooks / handoff（Repository-Native Playbooks / Handoff）

**状态：DP1 implemented**。本仓库现在携带 playbooks 与 agent 执行契约
（[DEVELOPMENT_PLAYBOOK.md](governance/DEVELOPMENT_PLAYBOOK.md)、
[RELEASE_PLAYBOOK.md](governance/RELEASE_PLAYBOOK.md)、
[AGENT_HANDOFF.md](governance/AGENT_HANDOFF.md)），未来任务引用它们而不是在每次
prompt 中重复完整 gate 规范。

### 4.5 Lifecycle-State Decoupling

Lifecycle-State Principle（第 6 节）：mutable lifecycle truth 不得作为
authoritative truth 固化进 immutable release payload。DP1 只记录这条规则；
具体的 release-state 设计（`release/state.json` 或等价物）是 DP5（语义设计
完成后）的工作。

### 4.6 CI 风险分层优化（CI Risk-Tier Optimization）

**状态：Phase 1 implemented**（分支 `ci/risk-tier-fast-path`）。实现为
[scripts/ci_risk_tier.py](../scripts/ci_risk_tier.py)（read-only、确定性、
无 network / GitHub API、fail-closed；pull_request 用 merge-base-correct
three-dot diff，push 用直连 tree diff；rename 的 old + new path 都计入；
验证见 [tests/test_ci_risk_tier.py](../tests/test_ci_risk_tier.py)）与
[.github/workflows/ci.yml](../.github/workflows/ci.yml) 的 step 级分类。

分类在每个正式 job（`test` / `portability-pyarrow24` / `package`）内以一个
`Classify change tier` step 运行，把 `CI_TIER` / `CI_TIER_REASON` 通过
`$GITHUB_ENV` 导出。不新增 job：仓库的 release-auditability 契约固定
CI 恰好有 4 个正式 job（`test`、`portability-pyarrow24`、`package`，
package 的依赖字面为 `needs: [test, portability-pyarrow24]`，且
`check_release.py` 断言 portability full-suite step 的 `run: python -m
pytest` 与 step name 字面相邻），该契约是既有 immutable invariant。
heavy steps 的 guard 为 `if: env.CI_TIER != 'docs_fast' && env.CI_TIER
!= 'package_docs' && env.CI_TIER != 'control_plane' && env.POST_MERGE_REUSE
!= 'true'`，并按 `matrix.python-version` 分腿：blanket FULL pytest 步骤
仅 `== '3.11'`，P1-1（§4.11）起 3.14 步骤为 audited compatibility
surface（验证器 + 表面执行）。**fail-safe 硬性要求**：没有条件表达式可以
让 unknown / unset tier 跳过 heavy validation——`CI_TIER` 未设置时 guard
恒为真，heavy validation 照常运行（等价 FULL）。fast-path marker
（`FULL_TESTS_SKIPPED_BY_POLICY` / `PACKAGE_BUILD_SKIPPED_BY_POLICY`）
只在 fast tier 出现。

例外（故意不带 tier guard）：package job 的 `Run release checker` step
在所有 tier 都执行。`scripts/check_release.py` 不是 package-build
检查器，而是 stdlib-only 的 release / document 一致性检查器，验证
`docs/**` 内容（release notes、direction、contracts、lifecycle
records）；docs 变更不得绕过优化前已存在的该检查。

三个保守 tier：

- **DOCS_FAST**：仅当所有 changed paths 属于 `docs/**` 或三个顶层 policy
  文档（`DEVELOPMENT_PLAYBOOK.md` / `RELEASE_PLAYBOOK.md` /
  `AGENT_HANDOFF.md`）时适用。保留权威 CI（checkout、changed-file
  分类、repo hygiene、whitespace / diff 检查、release checker /
  release-document 一致性检查），但**不运行** Python 3.11 blanket full
  pytest、Python 3.14 audited compatibility surface（§4.11）、PyArrow
  suite、package build / fresh-wheel smoke / SHA256 closure。target
  wall-clock ≤ 5 min（prefer ≤ 3 min）。
- **PACKAGE_DOCS**：所有 changed paths 属于 DOCS_FAST set + `README.md`，
  且至少 `README.md` 变更。`README.md` 是 package metadata 敏感路径
  （pyproject.toml `readme = "README.md"`），因此 package job 保持当前
  完整验证不变；跳过 Python 3.11 blanket full pytest、Python 3.14
  audited compatibility surface（§4.11）与 PyArrow suite。
- **FULL**：任何其他 changed path（`src/**`、`tests/**`、`scripts/**`、
  `examples/**`、`pyproject.toml`、`.github/workflows/**`、未知路径、
  混合变更等）、empty diff、classifier error —— 保持当前完整 CI 语义
  不变（P1-1 起：3.11 blanket FULL + 3.14 audited 294-node surface +
  PyArrow24 + package，见 §4.11）。**fail-safe 硬性要求**：unknown /
  unset tier 必须按 FULL 处理，任何条件表达式不得导致未知 tier 跳过
  重验证。

方向句保留：final-head CI 矩阵按变更风险分层，而不是每次变更统一运行每个
环境，同时为需要的变更保留权威的完整验证；该方向不削弱 final-head CI。
快路径的首次实测 wall-clock 在后续合法的 docs/policy-only PR 上记录，
不在本实现 PR 上声称达标。

### 4.7 Component-Aware Impact Classification（Foundation）

**状态：Phase 1 path-tier 已完成；本层为 component-aware impact
classification foundation（DP4 implemented）**。实现为
[ci/components.toml](../ci/components.toml)（组件注册表，read-only、
fail-closed）与 [scripts/ci_risk_tier.py](../scripts/ci_risk_tier.py)
的组件 impact 输出（稳定格式：`components=` / `core_changed=` /
`package_changed=` / `unknown_changed=` / `shared_changed=` /
`independent_only=` / `full_matrix_required=`）。

本层只建立安全扩展机制，不改变任何 tier：

- 保留 docs_fast / package_docs / full 三 tier；不新增正式 job。
- 注册表登记 `[components.core]`（`src/market_vault/`，
  `requires_core_full = true`）与 `[components.package]`
  （`pyproject.toml`、`README.md`，`requires_package = true`）。
- 控制面变更恒 FULL：`.github/workflows/**`、`scripts/ci_risk_tier.py`、
  `scripts/audit_pr.py`、`ci/components.toml`（registry 本身）、
  `pyproject.toml`（package schema）——future rule 条件 4。
- 未知路径恒 FULL（`changed_path_not_in_docs_scope`）。
- invalid registry / invalid ref fail closed（exit 2；
  `invalid_registry_fail_closed` / `classifier_error_fail_closed`）。
- CI 侧只在 `Classify change tier` step 导出 `CI_COMPONENTS`
  （`$GITHUB_ENV`）；不新增 job、不改 heavy-step guard、不启用任何
  skip。

**FUTURE RULE（已记录，未激活）**：以后只有当一个组件同时满足
（1）path 已显式注册、（2）有明确 component validation（未来注册表
扩展）、（3）不修改 core/shared contract、（4）不修改 package /
workflow / shared schema、（5）classifier 能确定影响范围——才允许
跳过旧 core full matrix。不能仅因为"路径不是 src/market_vault"就
自动认为安全。

**语义（foundation 阶段）**：`independent_only=` 只是 eligibility /
impact 信息——changed paths 结构性隔离于已注册的非 core / 非
package / 非 shared 组件——本身并不授权跳过 core full matrix。
`full_matrix_required=` 反映**当前 active 的 validation 策略**：
仅 docs_fast / package_docs 为 false，其余（core、unknown、
shared、以及无 validation 契约的 registered independent component）
恒为 true（与 tier 严格一致，杜绝
`component_without_validation_requires_full` 与
`full_matrix_required=false` 同时出现的矛盾状态）。只有未来 PR 落地
显式的 component-validation 契约后，才可能对该组件出现
`independent_only=true` 且 `full_matrix_required=false`。在注册表
声明 validation 之前，任何 registered-component-only 变更仍
classify FULL（`component_without_validation_requires_full`）。

**NO LIVE UI TIER YET**：本 PR 不得因为未来可能存在 `ui/` 就让
`ui/**` 进入 fast path。UI fast path 只有在真正创建 UI component
并同时定义它自己的 CI validation 时才启用；本 PR 不登记不存在的
ui component。

**SHARED CONTRACT（预留概念）**：未来 UI 若依赖 ArtifactClient，
UI-only PR 至少应执行 UI validation + ArtifactClient public contract
smoke，而不需要整个 Python core full suite。本 PR 只定义机制，不
伪造 UI contract。

### 4.8 Post-Merge Verified FULL Reuse（PR #61）

**状态：PR #61 implemented**。实现为
[scripts/ci_post_merge_reuse.py](../scripts/ci_post_merge_reuse.py)
（stdlib-only、read-only、无 `shell=True` / `eval` / 任意命令构造、无
repo/tag/ref mutation；纯验证核心与 GitHub REST adapter 分离、可离线
测试；验证见 [tests/test_ci_post_merge_reuse.py](../tests/test_ci_post_merge_reuse.py)）
与 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 的 step 级
gating。

对 eligible 的 main push，如果新 main 树被证明与一个成功完成的 final PR
FULL 运行 byte-for-byte Git-tree 等价，main CI 复用该验证证据并只跑轻量
post-merge 闭合（checkout、分类、whitespace、repo hygiene、release
checker、reuse marker）。任何 proof 缺失 / 歧义 / 过期 / 畸形 / 不可达
/ 失败 → FAIL CLOSED TO NORMAL FULL CI。"Reuse failure" 永远不让 CI
变弱。FASTER, SAME SAFETY。

九个条件（全部必须证明，任何一条失败即拒绝复用）：

1. 事件形状：`push` 事件、`refs/heads/main`、真实非零 `before`、真实
   main SHA。
2. Commit 拓扑：新 main commit 恰好一个 parent 且等于 `before`（单
   commit squash push；拒绝多 commit push、merge-commit push、root）。
3. 关联 PR：恰好一个 merged PR 关联到 exact 新 main commit
   （`merge_commit_sha` == main SHA、`base.ref` == main、PR 记录的 base
   SHA == `before`）；捕获 exact PR head SHA。
4. 成功 exact-head PR CI：相同 workflow 的 completed + success
   `pull_request` run，exact PR head SHA；queued / in_progress / failed /
   cancelled / skipped / neutral / timed_out / action_required 一律拒绝。
5. 所需 job：四个正式 surface（test (3.11)、test (3.14)、
   portability-pyarrow24、package）全部 terminal SUCCESS——不缺失、不
   重复、不额外、非成功即拒（job surface 变化而不更新契约 → fail
   closed）。job 拓扑不变；P1-1（§4.11）起 `test (3.14)` job 的内容为
   audited 294-node compatibility surface（验证器 + 表面执行），不再是
   blanket 3.14 full pytest。
6. Attestation：attempt-bound artifact 由该 exact run/attempt 产出，
   下载后严格 schema + 标识符交叉验证（repository、run_id、
   run_attempt、pr_number、base_sha、head_sha、tier=full、
   full_matrix_required=true 全部匹配已证明的上下文）。
7. **TREE EQUIVALENCE（核心安全证明）**：`git rev-parse <main
   sha>^{tree}` == attestation 的 `tested_tree_sha`。commit SHA 相等
   不被期望（合成 merge commit 与 squash commit 身份必然不同）；tree
   相等被要求——被测试内容的等价性。
8. 控制面排除：即使 tree 等价，变更触及 CI / release 安全控制面
   （`.github/workflows/**`、`scripts/ci_post_merge_reuse.py`、
   `scripts/ci_risk_tier.py`、`scripts/audit_pr.py`、
   `scripts/check_release.py`、`ci/components.toml`、
   `tests/test_v061_ci_auditability.py`、
   `tests/test_ci_post_merge_reuse.py` 及任何新的 attestation / gate
   contract 文件）→ FULL。rename 的 old + new path 都计入；changed
   paths 解析的未知错误 → FULL。
9. 失败语义：任何失败 → `POST_MERGE_REUSE=false reason=<specific>`，
   workflow 转 NORMAL FULL；verifier 失败本身不是 CI 失败；**没有任何
   状态可以导致 proof 失败 + 跳过 FULL 测试**（回归测试固定该不变式；
   `skip_heavy_validation` 只认字面 `"true"`）。

**Attestation**：pull_request + tier=full + full-matrix-required 的
package job 在全部 package 步骤成功之后创建 `ci_full_attestation.json`
——确定性 JSON（稳定 key 顺序、UTF-8、newline 结尾）、严格 schema
验证后才写出并上传为 attempt-bound artifact
`market-vault-full-ci-attestation-<head_sha>-attempt-<attempt>`。
attestation 只是证据，不取代 run/job conclusion 检查；缺失 attestation
永远不能启用复用；attestation 创建失败会 fail package job。docs_fast /
package_docs 不产出 attestation。

**Workflow gating**：不新增正式 job（保持恰好 4 个 formal job 与
`needs: [test, portability-pyarrow24]` 不变）。proof step 在
`github.event_name == 'push' && github.ref == 'refs/heads/main' &&
env.CI_TIER == 'full'` 时运行 verifier 并把 `POST_MERGE_REUSE` /
`POST_MERGE_REUSE_REASON` 通过 `$GITHUB_ENV` 导出；heavy step 的 guard
追加字面 `&& env.POST_MERGE_REUSE != 'true'`——unset 时是空串，guard
恒真，heavy validation 照常运行（fail-safe，与 §4.6 的 unknown tier
规则同构）。reuse marker（`FULL_TESTS_REUSED_FROM_VERIFIED_PR` /
`PACKAGE_VALIDATION_REUSED_FROM_VERIFIED_PR`）只在
`== 'true'` 时出现且只 echo；`Run release checker` 依旧无条件执行。
权限只读（`contents: read` / `pull-requests: read` / `actions: read`），
无任何 write；token 只送 `api.github.com`，artifact CDN 跨主机重定向
剥离 Authorization。`on:` 块无 paths / paths-ignore——复用 gate 绝不
通过 workflow 级路径过滤被绕过。

**控制面自排除**：本 PR 修改 CI 控制面（workflow + verifier + contract
测试 + 文档），因此它自己的第一次 main push 不允许使用 reuse gate，仍
要求完整 FULL；live reuse 路径只对后续普通 PR 生效。

**协议流程**：修改 → 本地验证（LEVEL 1/2，见 playbook 第 2 节）→
final-head push → final-head PR CI（tier 分层；tier=full 执行完整矩阵
并产出 attestation）→ 等 CI terminal → CC final PR report →
independent review → merge gate（final-head CI terminal SUCCESS +
独立审查通过 + 明确 merge 授权）→ squash merge → main verification
（**A — VERIFIED REUSE closure** | **B — NORMAL FULL fallback**）。
CC 必须等 exact main SHA 的 CI terminal（无论闭合 A 还是 B）之后才能
报告 COMPLETE；queued / waiting / pending / in_progress 一律不得报告
COMPLETE。

### 4.9 Partial Post-Merge Reuse V2 — Evidence Matrix Foundation（PR #65）

**状态：FOUNDATION ONLY / 未激活任何 production skip**。PR #65 只落地
纯数据模型与决策矩阵（在
[scripts/ci_post_merge_reuse.py](../scripts/ci_post_merge_reuse.py) 内，
`build_surface_reuse_plan` / `SurfaceDecision` / `ReusePlan` /
`render_reuse_plan`，全部 deterministic、无 I/O、无 GitHub / git / 环境
行为），**没有**接入 `run_verifier()`，ci.yml 也**没有**解析其输出。
V1 的 `POST_MERGE_REUSE=true/false` 语义、`render_verdict()` 输出、
`skip_heavy_validation`、attestation schema / field order、以及
`run_verifier()` 的完整四 surface 证明流程逐字节不变。任何 V2 输出都不
是生产 gate。

**三个未来模式**：`FULL_REUSE` / `PARTIAL_REUSE` / `NO_REUSE`，由
`ReusePlan.mode` 表达（`full_reuse` / `partial_reuse` / `no_reuse`）。

**Global identity 硬边界**：partial reuse 只在 global identity 已被独立
证明之后才被允许。identity 未证明 → `no_reuse`，4/4 surface
`reuse=false`、reason=`global_identity_unproven`；**不存在**
`identity_proven=false` 且任意 `surface.reuse=true` 的状态（回归测试固定
完整输入矩阵）。global identity 的完整含义（未来 caller 须等价建立）：
valid main push event、可信单 parent squash 拓扑、exact 关联 merged PR、
exact PR head/run 关联、valid attempt-bound attestation、attestation
标识符全部匹配、main tree == tested tree、无控制面排除。

**Canonical surface 模型**（固定顺序，独立于 V1
`REQUIRED_JOB_SURFACES`，后者原样保留）：

| surface ID | GitHub job name |
|---|---|
| `test-3.11` | `test (3.11)` |
| `test-3.14` | `test (3.14)` |
| `pyarrow24` | `portability-pyarrow24` |
| `package` | `package` |

**Per-surface evidence 规则**（identity 已证明且契约无歧义时）：surface
可复用 ⇔ 恰好一个对应 job 且 `status == completed` 且 `conclusion ==
success`（reason=`verified_job_success`）；缺失 →
reason=`job_missing`；存在但非 completed/success → reason=
`job_non_success`。这些缺失/非成功是 `PARTIAL_REUSE` 的正常来源——未来
workflow 只运行非可复用 surface。

**Ambiguity / 契约漂移规则（fail closed）**：重复的 canonical job
（reason=`job_duplicate_contract`）或 unexpected formal job（reason=
`job_unexpected_contract`）→ `no_reuse`，4/4 RUN。绝不围绕歧义的
workflow 契约做 partial reuse——延续 V1 "unknown control/evidence shape
fail closed" 原则。

**当前证据限制（明确声明）**：V1 的 global attestation 由 package job
在完整 PR FULL 链成功之后产出。因此本 foundation **不**声称可以从一个
从未产出 valid global attestation 的失败 PR run 中打捞独立成功的
surface。本 PR 语境下 `PARTIAL_REUSE` 的含义是：**GLOBAL TREE/PR/RUN
IDENTITY 已证明**，但个别 surface 证据缺失或非成功/不足；global
attestation / tree identity 无法证明 → `NO_REUSE` / FULL。未来若想打捞
"未走到 attestation 点的 PR run 中独立成功的 surface"，需要另行设计
per-surface attestation——本 PR 不声称该能力。

**历史 PR-#65 时代的计划 rollout 序列（historical，非当前激活计划）**：
#65 evidence model foundation → independent review → control-plane FULL
post-merge verification（#65 自身是控制面变更，其 main push 不得复用
证据）→ #66 实际 surface-level workflow gating → 专门 production
canaries / mutation cases。这是 PR #65 foundation 落地时规划的方向，
**不是**当前激活中的计划；后续独立决策见下方 "V2-A0" 小节。

**V2-A0 Post-Merge Activation Decision（2026-08-17）**

后续的独立架构评审（V2-A0）对 post-merge Partial Reuse V2 生产激活做出
了正式决策，永久记录于
[partial_reuse_v2_post_merge_activation_decision.md](partial_reuse_v2_post_merge_activation_decision.md)。
当前状态：

- P2-9 production-topology shadow canary 后来已成功完成（P2-9
  LIFECYCLE COMPLETE / PASS）。
- 该技术 PASS 本身并不授权激活。
- V2-A0 随后在现行 V1 precedence 与治理下审计了生产可达性与价值。
- V2-A0 正式结论 = **OUTCOME C**。
- Post-merge V2 生产激活被**刻意不采用**（`POST_MERGE_V2_ACTIVATION=
  DO_NOT_ACTIVATE`）。
- V2 foundation 保持存在且 UNWIRED。
- 当前没有任何生产 `if:` 消费 V2 输出。
- 未来重新考虑 post-merge 需要满足永久决策记录中 reopen criteria 的
  新一轮明确架构评审。
- PR-head reuse 是独立的方向，仅作为未来 research/design 方向，
  **此处不授权**（`PR_HEAD_REUSE_AUTHORIZED=false`）。

**PR-Head Reuse Phase-0B Product-Workload Decision（2026-08-18）**

后续的独立评审（Phase 0B）对 PR-head / PR 迭代复用进行了代表性产品
工作负载测量，永久记录于
[pr_head_reuse_phase_0b_product_workload_decision.md](pr_head_reuse_phase_0b_product_workload_decision.md)。
要点：

- Phase 0 初步发现了一个同类重复工作案例（尤其 PR #90），但样本以
  CI / P2 / 控制面工作为主。
- 独立评审要求测量有代表性的产品工作负载；Phase 0B 因此测量了 33
  个产品 PR。
- 多 head 产品开发是常见的（26/33 为多 head）。
- 大多数被观察到的 head 间变更是对代码/测试有实质影响（affecting）
  的变更。
- commit-chain 节点与可证明的远程 PR head 是两个不同的证据类别；
  在现有证据下，正确的观察数据集为 **78 个观察 head / 45 条观察
  转换**（`7b3e0b6` 目前为 `UNPROVEN_AS_REMOTE_PR_HEAD`）。
- 增量 docs-only 并不等于当前 workflow 是 docs_fast：当累计
  PR base->head 仍为 FULL 时，该 head 今天仍然运行 FULL。
- 这些累计-FULL 产品 head 情形下
  `ALREADY_SOLVED_BY_CURRENT_TIER_POLICY=0`。
- `INTERMEDIATE_PR_HEAD_REUSE_CANDIDATES=0`。
- `SAVEABLE_UNDER_FINAL_FRESHNESS=0`。
- Phase-0B 正式结论 = **OUTCOME C**。
- 不追求 PR-head 复用的实现/shadow 工作。
- `PR_HEAD_REUSE_AUTHORIZED=false`。
- 未来重新考虑必须满足新永久决策记录中的 reopen criteria。

**V2 未在生产实现。** 任何把 V2 输出当作生产 skip 依据的改动，必须先
通过上述完整评审与 canary 流程。

### 4.10 Control-Plane 验证层级（P1-2，PR #71）

CONTROL_PLANE 是第四种 CI tier：经过验证的保守子集路径（validated
SUBSET tier），介于 docs_fast / package_docs 与 FULL 之间。它只对
**精确的控制面 allowlist** 生效，绝不宽于 CI 自身验证面。

**精确 eligible path 哲学**：tier 资格只来自 `scripts/ci_risk_tier.py`
中的 `CONTROL_PLANE_SCOPE_RULES`（11 条精确路径；不存在
`tests/**` / `scripts/**` / `.github/workflows/**` 之类的宽规则）：

- `.github/workflows/ci.yml`
- `scripts/ci_risk_tier.py`
- `scripts/ci_post_merge_reuse.py`
- `scripts/audit_pr.py`
- `scripts/check_release.py`
- `ci/components.toml`
- `tests/test_ci_risk_tier.py`
- `tests/test_component_aware_tiers.py`
- `tests/test_ci_post_merge_reuse.py`
- `tests/test_audit_pr.py`
- `tests/test_v061_ci_auditability.py`

明确**不** eligible：`tests/test_release_v061.py`（bootstrap 安全）、
`pyproject.toml`、`README.md`、`scripts/check_repo_hygiene.py`、
`ci/python314_compatibility_surface.txt`、
`scripts/ci_python314_surface.py`、
`tests/test_python314_compatibility_surface.py`（P1-1 控制面路径，恒
FULL，见 §4.11）、`src/**`、其他 workflow、未知路径。混合规则：≥1 条
CP 路径 **且** 全部路径在 CP ∪ docs 范围内 → control_plane；任何越界
路径 → FULL。

**分类优先级（fail closed）**：empty → FULL；invalid → FULL；
docs_fast；package_docs；control_plane；shared/core/unknown → FULL。
control_plane 分支位于旧 shared_changed 检查**之前**，因此旧 shared
规则不会让精确 allowlist 子集不可达；allowlist 之外的改动仍命中
shared/core/violation 检查并保持 FULL。

**执行契约**（`.github/workflows/ci.yml`）：

- `Run conservative control-plane tests`：guard 精确等于
  `CI_TIER == 'control_plane' && matrix.python-version == '3.11'`，
  命令为字面六文件 pytest 面（`-q --durations=100`，无 `-k` /
  marker / glob）：`tests/test_ci_risk_tier.py`、
  `tests/test_component_aware_tiers.py`、
  `tests/test_ci_post_merge_reuse.py`、`tests/test_audit_pr.py`、
  `tests/test_v061_ci_auditability.py`、`tests/test_release_v061.py`；
- Python 3.14 在 control_plane 下**不**运行产品 FULL 套件；
- PyArrow24 六个 heavy 步骤与 package 十二个 heavy 步骤在
  control_plane 下 skip；
- `Prepare release-checker runtime`（`python -m pip install -e .`）在
  control_plane 下运行，`Run release checker` 保持无条件 → package
  checker tail 完整保留；
- 三个 formal job 均含 `Control-plane tier marker`。

**证据与复用边界**：

- `full_matrix_required=false`（validated subset，永不产出 V1 FULL
  证据）；
- 无 V1 attestation（create/upload 仅 `tier == 'full'`）；
- 无 V1 reuse proof（仅 main push + `tier == 'full'`）；
- unknown / unset / mixed 一律 fail closed FULL。

**Rollout 状态（精确）**：PR #71 仅部署机制（mechanism deployment）。
它自身因为修改 `tests/test_release_v061.py`（bootstrap safety）而
分类为 `tier=full, full_matrix_required=true`——这是有意的，绝不
"修复" classifier 让 #71 自身变成 control_plane。生产级 fast-path
验证需要独立的真实 canary：**PR #72 为首次生产 control-plane
canary**。在 canary 成功之前，不得声明 P1-2 生产验证完成，也不得把
#71 描述为 "production validated"。本 PR 的所有 wall-clock 记录属于
FULL 路径，不是 fast-path 基准。

### 4.11 Python 3.14 Compatibility Surface Activation（P1-1，PR #75）

**状态：PR #75 implemented（生产激活）**。P1-1 把经独立审核的 PR #74
Python 3.14 兼容性表面（audited 294-node compatibility surface）从
canary 测量永久部署为正式 FULL 契约的一部分。实现为永久 manifest
[ci/python314_compatibility_surface.txt](../ci/python314_compatibility_surface.txt)
（#74 已密封清单的逐字节拷贝：258 行 = 2 个 whole-file + 256 个 node
selector，normalized SHA-256 `2742853e…`）、fail-closed 验证器
[scripts/ci_python314_surface.py](../scripts/ci_python314_surface.py)
（stdlib-only、read-only、无 network / `shell=True` / eval；唯一 pytest
执行是 `--collect-only` 子进程且禁用 cache 与 bytecode 写入；验证见
[tests/test_python314_compatibility_surface.py](../tests/test_python314_compatibility_surface.py)）
与 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 的 3.11/3.14
分腿执行。

**新的正式 FULL 契约**（自本 PR 起，V1 attestation 证明的正是该契约）：

- `test (3.11)`：blanket FULL 产品 pytest（与 #74 之前完全一致）；
- `test (3.14)`：验证器通过后以 fail-closed Bash array 执行 audited
  294-node compatibility surface：`set -euo pipefail`；`mapfile` 从
  `ci/python314_compatibility_surface.txt` 载入显式数组
  `PY314_SELECTORS`；`test "${#PY314_SELECTORS[@]}" -eq 258` 硬校验
  selector 数；输出 `PY314_SELECTOR_COUNT` audit marker；打印全部
  selector；最后带引号展开为
  `python -m pytest "${PY314_SELECTORS[@]}" -q --durations=200`。
  不使用 command substitution（`$(cat ...)`）/ xargs / eval / glob /
  `-k` / marker / 动态 selector 发现；验证器任何失败 → 步骤失败，
  表面一行也不执行（fail closed）；
- `portability-pyarrow24` 与 `package` 与既有契约一致；
- job 拓扑不变：恰好 4 个 formal job，`package` 的
  `needs: [test, portability-pyarrow24]` 不变。

**Fail-closed 验证器**：每次 CI 运行在表面执行前从零验证，无 lockfile /
state。双 hash 钉死契约：

- manifest hash `2742853e…`：UTF-8、CRLF→LF 归一化（CRLF checkout 同样
  验证）、恰好一个 trailing LF、严格 selector 形状（无 glob / `-k` /
  `-m` / 目录 / 空白行；排序、去重、whole-file-node 不重叠）、固定
  计数（258 = 2 + 256）；
- resolved digest `7561b50a…`：`sha256(join(LF, sorted(collected
  nodeids)))`，与 #74 密封 digest 逐字节一致。parametrized selector 以
  `[param]` 后缀展开；selector 未 resolve、重复 node、计数 ≠ 294、
  digest 不符 → 全部 fail closed。成功 marker
  `PY314_SURFACE_VALIDATION_OK` 只在该步 stdout 输出，`check_release.py`
  同时以独立静态实现（不运行 pytest）把 workflow 分腿、步骤顺序、
  surface 步骤的 fail-closed Bash array 执行形态（mapfile / 258 计数
  校验 / `PY314_SELECTOR_COUNT` marker / selector 打印 / 带引号展开 /
  `--durations=200` / 禁止 `$(cat ...)`）与 manifest 静态契约钉死。

**Tier / reuse 边界**：三个 P1-1 路径（manifest、验证器、其测试）加入
`CONTROL_RULES`（FULL-forcing）而**不在** `CONTROL_PLANE_SCOPE_RULES`
——任何 P1-1 变更强制 FULL，绝不进入 control_plane fast path；
`ci_post_merge_reuse.py` 的 `CONTROL_PLANE_PATHS` 同样包含这三个路径，
触及即拒绝 post-merge 复用。

**Evidence 边界**：

- V1 attestation 证明**当前正式 FULL 契约完成**：3.11 blanket FULL +
  3.14 audited surface + PyArrow24 + package。**不**声称 Python 3.14
  blanket 产品 FULL pytest 运行过（schema_version=1，无 V2 字段）；
- `full_matrix_required=true` 对 P1-1 自身成立（控制面变更），本 PR 的
  wall-clock 记录属于 FULL 路径，标注为 TWO-RUN OBSERVED RANGE，不是
  stable benchmark；
- **Rollout 状态（精确）**：#74
  （[docs/python314_compatibility_surface_redesign_canary.md](python314_compatibility_surface_redesign_canary.md)）
  是独立的测量 / 设计 PR（canary，未激活）；#75 是生产激活，只部署
  #74 已审核的表面与机制，不改动表面本身。merge 由独立审查执行。

## 5. 未来 wall-clock 目标

这些是性能目标（performance targets），不是 correctness gates。未达到
目标不是验证失败，而是改进流程的信号。

| PR 类别 | 目标 wall-clock |
|---|---|
| small PR | 15–30 min |
| docs / policy-only small PR | 优先目标 ≤ 20 min |
| medium PR | 25–45 min |
| release-prep / complex | 40–60 min |

目标按类别区分：docs / policy-only 小 PR 的优先目标是 ≤ 20 min，比普通
small PR 更紧；release preparation 允许最宽松的目标。

如果优化后的 small / docs-only workflow 仍接近旧流程约 63 分钟的耗时，
应视为性能目标未达到，而不能把 63 分钟作为正常基准接受。旧流程观测值
只是 before 端参照（第 2 节），不是目标。

目标约束的是包括 final-head CI 在内的整个生命周期时间，不只是实现时间。

## 6. Lifecycle-State Principle

任何会在 merge、tag creation、Release publication、package publication
之后立即变假的陈述，都不能作为 authoritative current truth 固化进
immutable release payload。

区分两类 truth：

### IMMUTABLE SOURCE TRUTH

跨 lifecycle transition 仍然为真、可以作为 authoritative truth 放进
immutable release payload 的陈述：

- version
- feature scope
- API / contracts
- compatibility
- non-goals
- release procedure
- artifact formats

### MUTABLE LIFECYCLE TRUTH

在 lifecycle transition 发生的那一刻就翻转、绝不能作为 authoritative
current truth 固化进 immutable release payload 的陈述：

- PR open / current / merged
- current main HEAD
- tag-created state
- GitHub Release publication state
- Release ID / `published_at`
- latest status
- package-registry publication state

需要记录 mutable lifecycle truth 时（例如 release notes 文档），作为某个
时间点的历史记录、明确标注为历史记录——正如
[docs/release_v0_7_0.md](release_v0_7_0.md) 把正式 release 状态与历史的
release-preparation 记录分开。

## 7. DP1 范围边界

DP1：

- 记录 playbooks 与 agent 契约；
- 记录旧流程观测值、方向、目标与 Lifecycle-State Principle；
- 不修改产品代码、版本、依赖、public API、CLI、schema、artifact format
  或 CI workflow。

DP1 不实现 release-state 设计（`release/state.json` 或等价物）。那是 DP5
（语义设计完成后）的工作。
