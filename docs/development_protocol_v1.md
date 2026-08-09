# MarketVault Development Protocol v1

MarketVault 工程流程的架构 / roadmap 文档。本文档说明 Development Protocol
v1（DP1）的动机，记录优化前的旧流程观测值，并定义后续 PR 实现的方向。

- 策略文档：[DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md) 与
  [RELEASE_PLAYBOOK.md](../RELEASE_PLAYBOOK.md)。
- Agent 执行契约：[AGENT_HANDOFF.md](../AGENT_HANDOFF.md)。

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
[DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md) 第 2 节。

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
（[DEVELOPMENT_PLAYBOOK.md](../DEVELOPMENT_PLAYBOOK.md)、
[RELEASE_PLAYBOOK.md](../RELEASE_PLAYBOOK.md)、
[AGENT_HANDOFF.md](../AGENT_HANDOFF.md)），未来任务引用它们而不是在每次
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
!= 'package_docs'`（package job：`!= 'docs_fast'`）。**fail-safe 硬性
要求**：没有条件表达式可以让 unknown / unset tier 跳过 heavy validation
——`CI_TIER` 未设置时 guard 恒为真，heavy validation 照常运行（等价
FULL）。fast-path marker（`FULL_TESTS_SKIPPED_BY_POLICY` /
`PACKAGE_BUILD_SKIPPED_BY_POLICY`）只在 fast tier 出现。

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
  release-document 一致性检查），但**不运行** full pytest（Python 3.11 /
  3.14）、PyArrow suite、package build / fresh-wheel smoke / SHA256
  closure。target wall-clock ≤ 5 min（prefer ≤ 3 min）。
- **PACKAGE_DOCS**：所有 changed paths 属于 DOCS_FAST set + `README.md`，
  且至少 `README.md` 变更。`README.md` 是 package metadata 敏感路径
  （pyproject.toml `readme = "README.md"`），因此 package job 保持当前
  完整验证不变；跳过 full pytest 与 PyArrow suite。
- **FULL**：任何其他 changed path（`src/**`、`tests/**`、`scripts/**`、
  `examples/**`、`pyproject.toml`、`.github/workflows/**`、未知路径、
  混合变更等）、empty diff、classifier error —— 保持当前完整 CI 语义
  不变。**fail-safe 硬性要求**：unknown / unset tier 必须按 FULL 处理，
  任何条件表达式不得导致未知 tier 跳过重验证。

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
自动认为安全。`full_matrix_required=` 是该规则的机制化计算；在注册
表声明 validation 之前，任何 registered-component-only 变更仍
classify FULL（`component_without_validation_requires_full`）。

**NO LIVE UI TIER YET**：本 PR 不得因为未来可能存在 `ui/` 就让
`ui/**` 进入 fast path。UI fast path 只有在真正创建 UI component
并同时定义它自己的 CI validation 时才启用；本 PR 不登记不存在的
ui component。

**SHARED CONTRACT（预留概念）**：未来 UI 若依赖 ArtifactClient，
UI-only PR 至少应执行 UI validation + ArtifactClient public contract
smoke，而不需要整个 Python core full suite。本 PR 只定义机制，不
伪造 UI contract。

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
