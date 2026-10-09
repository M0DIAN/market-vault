# MarketVault 开发手册（Development Playbook）

MarketVault 的仓库级开发手册。Claude Code、Codex 以及人工开发者在执行任务
时引用本手册，而无需在每次 prompt 中重复完整的 gate 规范。

- PR 生命周期与本地验证层级：本文件。
- 正式发布流程：见 [RELEASE_PLAYBOOK.md](RELEASE_PLAYBOOK.md)。
- Agent 执行协议：见 [AGENT_HANDOFF.md](AGENT_HANDOFF.md)。
- 破坏性操作两阶段设计门：见
  [DESTRUCTIVE_OPERATIONS.md](DESTRUCTIVE_OPERATIONS.md)。
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

若范围涉及删除、隔离、覆盖、恢复覆盖、破坏性迁移或其他可能使持久状态不可用
的操作，实施前必须先完成独立的 design-only PR。实施 PR 的 base 必须已经包含
批准的机器可读合同；合同与首次实现不得位于同一个 PR。

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

PR 验证按第 2 节的 tier 分层。tier=full 的 PR 执行完整验证：Python 3.11
六个功能分片的全量离线套件、Python 3.14 审定兼容性 surface、PyArrow 24
可移植性 gate、package build /
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

### Windows 本地 FULL 安全入口

Windows 上需要运行本地完整离线套件时，唯一标准入口是：

```powershell
.\scripts\verify_full.ps1
```

不要在 MarketVault 仓库或任何已注册 Git worktree 内使用 `--basetemp`
运行 FULL pytest，包括 `.pytest_cache/full`。测试可能递归复制仓库；worktree
内的 basetemp 会让复制包含自身，导致递归增长和磁盘耗尽。

wrapper 从脚本位置和 Git 元数据发现当前仓库，通过
`git worktree list --porcelain` 核验所有已注册 worktree。每次运行使用唯一
run ID，并优先选择 `D:\MarketVault-TestTemp\<run-id>`；D: 不可用时才选择
安全的仓库外平台目录。启动 pytest 前要求实际 basetemp 所在文件系统至少有
10 GiB 可用空间。任何路径归属或磁盘空间无法证明时均拒绝运行。

可使用绝对路径覆盖共享 temp parent：

```powershell
$env:MARKET_VAULT_TEST_TEMP_ROOT = "E:\MarketVault-TestTemp"
.\scripts\verify_full.ps1
```

覆盖路径仍执行相同的 worktree containment 和磁盘检查，不能绕过安全规则。
wrapper 仅删除本次 `<run-id>` 目录，不删除共享 parent。Windows ACL 或文件锁
导致清理失败时，它会报告并保留该精确 run 目录，不扩大删除范围。该入口不
改变 pytest 的测试选择，并禁用 worktree 内 pytest cache 写入；focused
development 仍可直接运行指定测试文件。

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
  （[.github/workflows/ci.yml](../../.github/workflows/ci.yml)）：Python 3.11
  完整功能分片与 Python 3.14 兼容性验证、PyArrow 24 可移植性 gate、以及 package
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

- **DOCS_FAST**：仅 `docs/` 范围内文档变更（包括
  `docs/governance/` 下的 DEVELOPMENT_PLAYBOOK.md /
  RELEASE_PLAYBOOK.md / AGENT_HANDOFF.md）；分类器仍保留三个历史
  root-level policy filename 的兼容 allowlist，但当前正式文件均位于
  `docs/governance/`。不跑 full pytest / PyArrow suite / package build，
  但保留分类、whitespace、repo hygiene 与 release checker（release /
  document 一致性检查），target ≤ 5 min（prefer ≤ 3 min）。
- **PACKAGE_DOCS**：DOCS_FAST set + `README.md` 变更（README 是 package
  metadata 敏感路径）—— package job 保持完整验证。
- **CONTROL_PLANE**：分类器中明确列出的十个 CI 治理文件及文档的组合，
  执行既有六文件控制面回归。工作流 `ci.yml`、3.11 分片清单与执行器、
  3.14 兼容性契约不属于此快速范围。
- **RESEARCH_FAST**：PR 中符合既有研究路径规则的变更，执行固定研究组合；
  该业务组合在 Python 3.11 执行，Python 3.14 执行第 2.5 节的兼容性范围。
  main 的相同变更仍要求 FULL。
- **FULL**：任何其他变更 —— 完整验证范围不减。unknown / unset tier
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
组件注册本身不授权跳过 core CI；只有上文明确验证的路径 tier 可以采用
对应快速组合。unknown 路径、执行工作流、分片契约和 package schema
变更仍要求 FULL。core 组件 `requires_core_full`，package 路径由
package job 覆盖。`independent_only=` 只是
eligibility / impact 信息（changed paths 结构性隔离于已注册的非
core / 非 package / 非 shared 组件），本身并不授权跳过 core full
matrix；`full_matrix_required=` 反映当前 active 的 validation 策略
——docs_fast / package_docs / control_plane / research_fast 为 false，
FULL 为 true。没有 validation 契约的 registered independent component
仍要求 FULL。只有未来 PR 落地显式的 component-validation 契约后，才
可能对该组件出现 `independent_only=true` 且
`full_matrix_required=false`。

### 2.4 Python 3.11 FULL 的功能分片

PR 与 main push 使用同一套分片规则；`plan` job 是整次运行唯一的分类和
复用证明来源。FULL 且未受证复用时，同时运行下列六片。每片保留完整
checkout，只改变 pytest 的文件选择，片内仍按原方式顺序执行。

| 分片 | 功能边界 |
|---|---|
| `data` | 采集、Canonical、审计、清理、日内数据准备及桌面入口 |
| `dataset_features` | Dataset、PIT、多源、跨日、特征与样本生成 |
| `strategy` | 策略研究、诊断、比较、回测、执行及对应桌面入口 |
| `intraday_research` | 日内研究与实验及对应桌面入口 |
| `intraday_final` | 日内最终 TEST 及对应桌面入口 |
| `app_ops` | 通用桌面、启动、CI、打包、治理与其余历史回归 |

[ci/test_partitions.toml](../../ci/test_partitions.toml) 以精确文件优先、
随后前缀匹配的规则分配测试；新增陌生名称、重复归属、空分片或发现规则
变化会直接失败。所有发现的测试文件必须恰好归属一片。分片规则变更时，
还应在相同依赖环境中比较原完整 collection 与六片 collection 的 node-id
多重集，确认没有漏测或重复收集。执行器拒绝继承 `PYTEST_ADDOPTS`，防止
环境过滤或 collect-only 把完整执行变成成功的空验证。

稳定检查名 `test (3.11)` 在 FULL 路径汇总六片结果；只有计划成功且整个
分片矩阵成功才通过。快速路径或受证复用必须对应按计划跳过的分片。
`package` 保持成功依赖，任何必要验证失败都不能生成 FULL attestation。
复用校验除四个原逻辑验证面外，还要求 `plan` 和全部六片在同一 PR
run/attempt 上成功。执行契约变更禁止沿用旧证据，main 会实际运行 FULL。

首版最多并发六片，不同时引入片内多进程。研究与最终 TEST 分开以降低
最长片耗时；实际等待时间由最慢片、runner 排队、兼容性与打包尾部决定。
保留原双 Python `test` 矩阵意味着 3.14 在六片后运行。12–15 分钟是首轮
FULL 的优化目标，须以真实 CI 验证，不能把六片宣称为固定六倍加速。
PR 的后续推送取消旧 PR 运行；main 的每个自然 push 保留独立运行身份。

### 2.5 Python 3.14 的兼容性范围

Python 3.14 的 FULL 与 RESEARCH_FAST 路径使用同一兼容性定义：

| 范围 | 执行方式 | 主要边界 |
|---|---|---|
| 原有兼容性基线 | 原 258 selectors，解析为 294 nodes，先验证 count 与 digest 再执行 | 解释器、导入/CLI、时间戳/时区、路径、pandas/PyArrow/DuckDB 读写与类型 |
| `tests/test_ml_dataset_adapter.py` | 完整文件，当前 14 nodes | 研究数据投影、pandas float64/int64、列顺序及输出拷贝隔离 |
| `tests/test_ts2_feature_boundaries.py` | 完整文件，当前 11 nodes | 静态注册实现、inspect 签名/源码、CRLF 规范化、fingerprint、冻结 dataclass |

两个补充文件与原 sealed manifest 分开执行；原基线的 selector 数、294-node
解析结果及两个 digest 保持原有身份。研究边界文件按完整文件执行，新加
边界用例自动包含在内。成功 marker `PY314_RESEARCH_COMPATIBILITY_OK`
仅在两个补充文件执行成功后输出。

RESEARCH_FAST 的既有 21 文件业务组合及其成功 marker 限于 Python 3.11。
main 的研究变更仍执行 Python 3.11 六片 FULL，3.14 使用上述同一兼容性
范围。其他快速 tier 和受证复用遵循原有跳过策略。

ML Adapter 的小型 fixture 包含实际 PIT、Observation、TS2、跨日 join 与
pandas 投影；它替换了最终 verified artifact loader，因此这一补充验证的
范围是运行时数据边界，完整磁盘产物与业务回归仍由 3.11 FULL 承担。

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
