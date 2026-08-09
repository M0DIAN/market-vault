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

脚本化的 PR audit，机械地检查冻结范围契约（changed-file list 与 scope
一致、无 product / version / dependency / API / CLI / schema / workflow
变更），无需人类或 agent 重读整个 diff。audit 是审查的机械部分；
independent review 仍由人类或独立审查者判断。

### 4.4 仓库原生 playbooks / handoff（Repository-Native Playbooks / Handoff）

本仓库现在携带 playbooks 与 agent 执行契约
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

final-head CI 矩阵按变更风险分层，而不是每次变更统一运行每个环境，同时为
需要的变更保留权威的完整验证。该方向不削弱 final-head CI；它作为独立变更
规划与审查。

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
