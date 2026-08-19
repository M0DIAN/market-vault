# MarketVault 开发手册（Development Playbook）

MarketVault 的仓库级开发手册。Claude Code、Codex 以及人工开发者在执行任务
时引用本手册，而无需在每次 prompt 中重复完整的 gate 规范。

- PR 生命周期与本地验证层级：本文件。
- 正式发布流程：见 [RELEASE_PLAYBOOK.md](RELEASE_PLAYBOOK.md)。
- Agent 执行协议：见 [AGENT_HANDOFF.md](AGENT_HANDOFF.md)。
- 动机与路线图：见
  [docs/development_protocol_v1.md](../development_protocol_v1.md)。

本手册是 Development Protocol v1（DP1）的策略。DP1 只定义策略，不修改 CI、
测试或工具链；后续 PR 负责实现。

## 1. 标准 PR 生命周期

每个 MarketVault PR 都遵循同一个生命周期。顺序重要，gate 不可协商。

### 1.1 精确基线（Exact Base）

1. `git switch main`
2. `git fetch origin --prune --tags`
3. `git pull --ff-only`
4. 验证 `HEAD == origin/main == <exact base SHA>`（任务给定的 exact base
   SHA，或当前 main HEAD）。
5. 验证工作区干净（`git status --short` 无输出）。

任一检查失败即停止并报告。绝不允许从未经验证的基线开始工作。

### 1.2 范围冻结（Scope Freeze）

编辑前先明确任务范围：允许修改的文件、禁止修改的文件、以及 non-goals。
范围有歧义时与任务方确认。

冻结的范围是承诺。未经明确批准扩大范围属于违反协议
（见 [AGENT_HANDOFF.md](AGENT_HANDOFF.md) 规则 4）。

### 1.3 创建分支

创建反映变更内容的分支，例如 `docs/development-protocol-v1`。分支推送到
远端，以便 final-head CI 运行。

### 1.4 实现

在分支上实现冻结的范围。保持与周围代码一致的风格与注释密度。不得静默添加
相邻工作。

### 1.5 本地验证层级

运行合适的本地验证层级（第 2 节）。按变更规模与风险选择层级，而不是规定
"每次编辑都必须跑全部"。

### 1.6 final-head push

`git push -u origin <branch>` 推送 final head。

final head 是你希望审查者评估的最后一个 commit。此后一切评估都针对这个
exact SHA。

### 1.7 GitHub final-head CI

PR 会为 exact final head SHA 触发 GitHub Actions。final head 的权威验证是
CI（见 2.3）。CI 未到达 terminal 状态前不得报告完成——见
[AGENT_HANDOFF.md](AGENT_HANDOFF.md) 的 CI-wait 报告规则。

PR 验证按第 2 节的 tier 分层。tier=full 的 PR（含任何 CI 控制面变更、
`src/**`、`tests/**`、`scripts/**` 变更）执行完整矩阵：Python 3.11 /
3.14 全量离线套件、PyArrow 24 可移植性 gate、package build /
fresh-wheel / SHA256 closure。tier=full 且 full-matrix-required 的 PR
运行在 package job 全部成功后会产出 **FULL CI attestation** artifact
（`market-vault-full-ci-attestation-<head_sha>-attempt-<attempt>`，
确定性 JSON，记录被测试的 exact merge commit tree SHA），作为后续
post-merge 复用验证的证据；docs_fast / package_docs 的 PR 不产出
attestation。attestation 只是证据，不取代任何 run/job conclusion 检查。

### 1.8 独立审查（Independent Review）

由独立审查者——人类或独立的审查进程，绝不能是撰写该工作的 agent——审查
final head：diff、scope audit、CI 结果、以及任何 release 影响。撰写该工作
的 agent 自己的报告不构成 independent verification。

### 1.9 merge gate

只有以下条件全部满足才可 merge：

- final-head CI 已 terminal 且 SUCCESS，并且
- 独立审查通过，并且
- 获得了明确的 merge 授权。

STOP BEFORE MERGE，除非获得明确授权。

### 1.10 main verification

merge 后，push 到 `main` 会为 merge commit 触发 main CI。main CI 是权威的
post-merge 验证。报告 COMPLETE 的任务必须先等 exact merge/main commit 的
CI 到达 terminal 状态（与 1.7 相同规则）。

main verification 有两种闭合路径（Post-Merge Verified FULL Reuse，
[scripts/ci_post_merge_reuse.py](../../scripts/ci_post_merge_reuse.py)，
详见 [docs/development_protocol_v1.md](../development_protocol_v1.md)
第 4.8 节）：

- **A — VERIFIED REUSE closure**：当新 main 树被证明与一个成功完成的
  final PR FULL 运行 Git-tree 等价（verifier 全部条件成立，
  `POST_MERGE_REUSE=true`），main CI 复用该验证证据并只跑轻量 post-merge
  闭合（分类、whitespace、repo hygiene、release checker、reuse marker）。
  复用要求树等价，**不要求 commit SHA 相等**（squash commit 与合成 merge
  commit 身份必然不同；tree 相等才是被测试内容的等价性）。
- **B — NORMAL FULL fallback**：任何证据缺失 / 歧义 / 过期 / 畸形 /
  不可达 / 失败，或变更触及 CI 控制面（workflow、classifier、release
  checker、audit、registry、gate contract 文件），main CI 退化为正常
  完整 FULL 验证。

**Reuse failure 永远不是 CI 失败，也永远不会跳过验证（fail-closed）**。
控制面变更的 main push 恒走 FULL（本 PR 自己的第一次 main push 即如此）。

## 2. 本地验证层级

三层定义本地需要跑多少验证。高层包含低层。

### LEVEL 1 — focused development

用于开发迭代，快速反馈：

- 只跑与修改行为直接相关的测试。
- 只跑与 changed paths 相关的 checker / lint / diff 检查
  （例如 `git diff --check`、对修改文件 `python -m compileall`、与修改面
  相关的 repo hygiene 检查）。

### LEVEL 2 — submission readiness

提交 final head / 打开或更新 PR 之前：

- affected regression surface：覆盖被修改代码路径的 regression suite，
  跑完。
- scope audit：changed-file list 与冻结范围完全一致。
- dependency / version audit when applicable：任何涉及依赖、打包或版本的
  变更必须验证其影响的 dependency 与 version 面。

不能仅仅因为存在 PR 就自动要求完整本地套件。小文档 PR 或单模块 PR 不自动
要求完整本地套件。

提交前可运行机械 scope audit 工具（DP2 implemented，
[scripts/audit_pr.py](../../scripts/audit_pr.py)）：

```
python scripts/audit_pr.py --base <base> --head <head> --allow <path_or_prefix> ...
```

它只检查 changed-file list 与显式 allow 规则是否一致（read-only，不访问
GitHub / network），是 scope audit 的机械部分；independent review 仍由人类
或独立审查者判断。详见 [docs/development_protocol_v1.md](../development_protocol_v1.md)
第 4.3 节。

### LEVEL 3 — authoritative full verification

- GitHub final-head CI，按仓库策略
  （[.github/workflows/ci.yml](../../.github/workflows/ci.yml)）：完整测试矩阵
  （Python 3.11 与 3.14）、PyArrow 24 可移植性 gate、以及 package
  build / fresh-wheel / SHA256 closure job。
- merge 前（适用时）的权威验证。完整矩阵的权威从来不在本地机器，而是
  GitHub final-head CI。
- post-merge 的权威验证是 main CI：tier=full 的 main push 先运行
  post-merge reuse proof——证明成功则复用已验证的 PR FULL 证据（闭合
  A），证明失败则执行正常完整 FULL 验证（闭合 B）。两条路径都必须
  terminal 之后才允许报告 COMPLETE（见 1.10）。

final-head CI 按 changed paths 分层（CI Risk-Tier Optimization Phase 1，
详见 [docs/development_protocol_v1.md](../development_protocol_v1.md)
第 4.6 节）：

- **DOCS_FAST**：仅 `docs/` 与三个顶层 policy 文档（DEVELOPMENT_PLAYBOOK.md /
  RELEASE_PLAYBOOK.md / AGENT_HANDOFF.md）变更 —— 不跑 full pytest /
  PyArrow suite / package build，但保留分类、whitespace、repo hygiene
  与 release checker（release / document 一致性检查），
  target ≤ 5 min（prefer ≤ 3 min）。
- **PACKAGE_DOCS**：DOCS_FAST set + `README.md` 变更（README 是 package
  metadata 敏感路径）—— package job 保持完整验证。
- **FULL**：任何其他变更 —— 当前完整矩阵不变。unknown / unset tier
  一律按 FULL 处理（fail-safe）。

分类由 [scripts/ci_risk_tier.py](../../scripts/ci_risk_tier.py) 完成
（read-only、fail-closed）。

分类是分层的：Phase 1 path-tier（docs_fast / package_docs / full）
已完成；下一层是 component-aware impact classification
（[docs/development_protocol_v1.md](../development_protocol_v1.md)
第 4.7 节）。组件注册表 [ci/components.toml](../../ci/components.toml)
登记组件路径面，分类器额外输出组件 impact（`components=` /
`core_changed=` / `package_changed=` / `unknown_changed=` /
`shared_changed=` / `independent_only=` / `full_matrix_required=`）。
独立组件未来可避免无关 core CI，但 unknown / shared（workflow、
classifier、registry、package schema）变更必须 FULL。当前没有任何
组件可跳过验证：core 组件 `requires_core_full`，package 路径由
package job 覆盖，控制面变更恒 FULL。`independent_only=` 只是
eligibility / impact 信息（changed paths 结构性隔离于已注册的非
core / 非 package / 非 shared 组件），本身并不授权跳过 core full
matrix；`full_matrix_required=` 反映当前 active 的 validation 策略
——仅 docs_fast / package_docs 为 false，其余（core、unknown、
shared、以及无 validation 契约的 registered independent component）
恒为 true。只有未来 PR 落地显式的 component-validation 契约后，才
可能对该组件出现 `independent_only=true` 且
`full_matrix_required=false`。

## 3. 何时不要求本地完整 pytest

当权威的 final-head CI 会执行完整矩阵时，每次小修改后并不是默认要求本地
完整 `pytest` 运行。

final head 的权威完整验证是 GitHub CI。本地完整套件在 CI 覆盖它时是可选的；
本地验证的目的是快速、尽早发现问题（LEVEL 1）并证明提交就绪（LEVEL 2），
而不是在每次编辑时复制整个 CI 矩阵的工作。

以下情况仍然适合本地完整套件：

- CI 不可用（例如仓库网络故障），或
- 变更属于 release-preparation，必须在 release gate 前验证，或
- 任务明确要求本地完整运行。

## 4. DP1 当前不修改 CI

DP1 不改 CI 行为。[.github/workflows/ci.yml](../../.github/workflows/ci.yml)
定义的 final-head CI——完整矩阵、PyArrow 24 gate、package job——保持原样，
不被削弱。任何未来的 CI 变更都是独立的、带自己审查的 PR。
