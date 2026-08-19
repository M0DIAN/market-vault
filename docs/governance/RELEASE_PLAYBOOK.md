# MarketVault 发布手册（Release Playbook）

MarketVault 的仓库级正式发布流程。本文件记录每个 MarketVault release 必须
通过的正式 release gate。当前正式发布流程是在 v0.3.0 到 v0.7.0 的实践中
逐步完善的，其中 v0.7.0 是当前完整独立审计过的参考发布流程；已记录的
v0.7.0 示例见 [docs/release_v0_7_0.md](../release_v0_7_0.md)。

## 1. 正式 release gate

MarketVault 正式发布是以下 gate 按顺序组成的序列。所有 gate 通过、最终
状态记录到 release record 中之前，release 不算完成。

### 1.1 exact release commit

release commit 是 main 上 CI 通过且内容被发布的 exact commit——例如
v0.7.0 release commit `f25a50481b5ee718881acf5cb5ea5aa05bd32d93`。任何
release 步骤之前必须明确验证 release commit SHA。

### 1.2 clean detached / fresh build environment

打包与发布验证在 exact release commit 的干净 detached checkout 中进行
（`git checkout --detach <SHA>`），绝不在带未提交变更的工作分支、也绝不在
过期的构建目录中进行。wheel 与 sdist 在此环境中全新构建。

### 1.3 只有 merge / main verification 之后才能创建 tag

annotated release tag 只有在以下条件满足后才创建：

- release PR 已 merge，且
- exact merge commit 的 main CI run 已成功。

绝不允许基于 PR 状态、分支状态或未经验证的 main 状态创建 tag。

### 1.4 annotated tag identity

release tag 是 annotated tag（`git tag -a <version> <SHA>`），在 merge 与
main verification 之后创建，指向 exact release commit。peeled tag commit
必须等于 release commit。tag 名称、tag object SHA 与 tag 类型在发布发生后
记录到后续 main 的 release record 中（见第 3 节）。

### 1.5 正式 GitHub Release asset identity

GitHub Release 恰好发布三个资产：wheel、sdist、per-package
`SHA256SUMS.txt` manifest。Release ID、`publishedAt` 时间戳、`draft: false`
/ `prerelease: false` 在发布发生后记录到后续 main 的 release record 中
（见第 3 节）。

### 1.6 wheel / sdist validation

上传之前：恰好一个 wheel 与一个 sdist 存在，`twine check` 通过，wheel
能在全新 virtual environment 中安装，CLI `--version` / `--help` 表面在
fresh wheel 上可用，fresh-wheel public API import smoke 通过。

### 1.7 fresh-wheel smoke

关于发布产物的每条正式断言都必须针对全新构建的 wheel 验证，绝不对
editable source checkout 验证。

### 1.8 SHA256 closure

计算每个正式资产的 SHA-256，用实际字节验证 per-package `SHA256SUMS.txt`
manifest，把资产上传到 GitHub Release，再下载回来并重新验证哈希。记录的
哈希就是正式 Release 资产的哈希。

### 1.9 哈希类别（Hash Classes）——三个类别必须分清

| 类别（英文名稳定） | 含义 |
|---|---|
| PR candidate hashes | release-preparation 分支 / PR 上构建并验证的产物哈希。仅 candidate 验证。 |
| Main CI audit hashes | exact merge commit 的 main push CI package audit run 产生的哈希。post-merge 验证记录。 |
| Formal Release asset hashes | merge 与 main verification 后，从 exact release commit 重新构建的最终资产的哈希，下载回来后重新验证。正式发布记录中的 authoritative hashes。 |

PR candidate hashes 绝不能当作 Formal Release asset hashes 使用。正式资产
在 merge 与 main verification 后从 exact release commit 重新构建，无论 PR
CI 构建过什么。

### 1.10 PyPI / TestPyPI 发布永远是独立显式决定

发布到 PyPI 或 TestPyPI 是在上述正式 release gate 之后单独做出的显式决定，
绝不是 tagging 或 GitHub Release 的自动结果。每次发布决定（PUBLISHED 或
NOT PUBLISHED）记录在 release record 中。

### 1.11 不得为修复文档问题在发布后 rebuild / re-upload / 移动 tag

已发布的 tag、已发布的 GitHub Release 及其资产，不得为修复文档、措辞或
外观问题而重建、重新上传或移动。修复属于后续 main 变更与后续 release。

## 2. 不可变发布原则（Immutable-Release Principle）

已发布 / 已打 tag 的 release 产物是不可变记录。

发布后的修正属于后续 main，除非实际发布的产物本身无效。产物无效指发布的
字节与记录的 identity 不符或未通过正式 gate——例如损坏的上传、错误的文件、
损坏的 wheel。措辞、排版或文档质量问题绝不是变更 release 的理由。

## 3. release 状态记录与 lifecycle-state timing

发布之后，mutable lifecycle 事实作为明确的 point-in-time / historical
release record 记录到可以继续演进的 main 上——例如
[docs/release_v0_7_0.md](../release_v0_7_0.md) 已有的模式：正式状态小节
与历史 release-preparation 记录小节分开。

tag-created state、tag object SHA、GitHub Release publication state、
Release ID、`publishedAt`、PyPI / TestPyPI publication state、current
main HEAD 等事实在发布发生后记录到后续 main 的 release record 中。不得
暗示这些内容必须已经存在于 tagged release commit 中：它们只能由 lifecycle
transition 本身产生，不可能作为 authoritative current truth 预先存在于
immutable release payload。

### 3.1 immutable release payload 中只能有稳定事实

IMMUTABLE RELEASE PAYLOAD（release commit / tag / package）中作为
authoritative current truth 的内容只能是稳定事实，例如：

- version
- feature scope
- API / contracts
- compatibility
- non-goals
- release procedure
- artifact formats

以下 mutable lifecycle facts 不得要求预先存在于 immutable release commit
/ tag / packaged README / wheel metadata 中：

- current main HEAD
- PR open / current / merged
- tag-created state
- tag object SHA
- GitHub Release publication state
- Release ID
- publishedAt
- latest status
- PyPI / TestPyPI publication state

因为这些事实只有 lifecycle transition 发生后才能知道。

### 3.2 post-release main 可以领先于 tag

发布完成后，post-release main 正常情况下可以并且经常会领先于 immutable
release tag：tag 与它的 payload 在 release commit 处冻结，后续 main 携带
historical release record 与后续工作。这不是 release identity drift。

### 3.3 DP1 不实现 release-state 设计

不要设计 `release/state.json`，不要实现机器可读 release-state。那是 DP5
（语义设计完成之后）的工作。

## 4. 普通 PR 的发布相关卫生

- version 变更、dependency 变更与正式 release-state 声明属于
  release-preparation PR，不属于 feature PR。
- PR 不得移动或重建 release tag，不得改动 release 资产或已密封的 release
  记录（见 [AGENT_HANDOFF.md](AGENT_HANDOFF.md) 规则 6 和 7）。
