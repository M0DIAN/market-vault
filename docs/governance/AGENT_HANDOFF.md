# MarketVault Agent 执行协议（Agent Handoff）

Claude Code 与 Codex agent 在 MarketVault 仓库工作的执行契约。Agent 遵循本
契约，而无需在每次 prompt 中接收完整 gate 规范。所引用的手册：
[DEVELOPMENT_PLAYBOOK.md](DEVELOPMENT_PLAYBOOK.md) 与
[RELEASE_PLAYBOOK.md](RELEASE_PLAYBOOK.md)。

## 1. 执行契约

1. **Agent 是 executor，independent reviewer 必须独立。** Agent 负责实现与
   验证。独立审查者——人类或独立审查进程，绝不能是同一 agent 实例——负责
   批准。
2. **Agent 自己的报告不能替代 independent verification。** Agent 的
   "我检查过了" 不是审查 gate。独立审查 gate（开发手册 1.8）只能由撰写该
   工作的 agent 之外的审查者满足。
3. **开始工作前必须验证 exact base SHA。** 执行精确基线流程（开发手册
   1.1）：`git switch main`、`git fetch origin --prune --tags`、
   `git pull --ff-only`、验证 `HEAD == origin/main == <base SHA>`、验证
   工作区干净。失败则停止并报告。
4. **scope expansion 必须 STOP 并报告，不得静默扩大范围。** 若工作中发现
   冻结范围错误或不完整，停止并报告需要的扩展，不得擅自并入。
5. **STOP BEFORE MERGE unless explicitly authorized.** Agent 未经明确 merge
   授权绝不 merge 自己的 PR。
6. **release tag 不得自行创建 / 删除 / 移动 / 重建。** 除明确 release 任务
   外，不得创建、删除、移动或重建任何 tag。
7. **release history 不得自行 amend / rebase / force-push。** release
   commit、tag 与正式 release 记录不可变（发布手册第 2 节），未经明确授权
   不得 amend / rebase / force-push 受保护的 release history。

## 2. 最终报告规则：等待 CI 到达 terminal 状态

这是最重要的报告规则。

任务一旦触发 GitHub CI，Agent 必须等待与该任务 exact final head SHA 对应的
CI 到达 terminal 状态。

在 CI 处于以下状态时，Agent 不得输出 final acceptance / completion report：

- queued
- waiting
- pending
- in_progress

只有当 exact final head SHA 对应的 CI 到达 terminal 状态后：

- **terminal SUCCESS**
  -> 报告 `READY FOR INDEPENDENT REVIEW`（附第 3 节的标准 final-report
     字段）。

- **ANY terminal non-success conclusion**
  -> 报告 `FAILED` 或 `BLOCKED`。
  -> 任何 terminal non-success 状态都绝对不能变成 `READY FOR INDEPENDENT
     REVIEW`。

terminal non-success 包括但不限于：

- failure
- cancelled
- timed_out

报告 terminal non-success 时必须包含：

- actual workflow conclusion
- affected job(s)
- failing / terminated step when available

如果任务随后 merge 并触发 main CI，对 exact merge/main commit 应用完全
相同的规则后再报告 `COMPLETE`：只有 terminal SUCCESS 才能 COMPLETE，否则
`FAILED` / `BLOCKED` 并附 actual conclusion 与 affected job / step。

Do not drip-feed "CI pending" as a final report.

可以有普通进度消息，但正式 final report 只能在 CI 到达 terminal 状态后输出。

## 3. 标准 final-report 字段

每个 final report 按顺序包含以下字段（字段名保持稳定英文）：

| 字段（英文名稳定） | 内容 |
|---|---|
| base SHA | 开工前验证的 exact base SHA |
| final head SHA | 被评估的 pushed head SHA |
| changed files | 精确的 changed-file list |
| local checks | 执行的本地验证及其结果 |
| CI run ID | final head 对应的 GitHub Actions run ID |
| CI job conclusions | 每个 job 的实际结论（SUCCESS，或 terminal non-success 时的 failure / cancelled / timed_out 等） |
| diff / scope result | diff stat，以及 changed-file list 与冻结范围一致的确认 |
| working-tree state | clean，或确切的剩余变更 |
| mutation / immutability declaration | 当属实时明确声明：无 product / version / dependency / API / CLI / schema / workflow / release 变更 |
| stop state | 当前停止点（例如 STOP BEFORE MERGE、READY FOR INDEPENDENT REVIEW） |

## 4. 报告词汇

- `READY FOR INDEPENDENT REVIEW` — final-head CI terminal SUCCESS，本地
  检查与 scope 检查全部完成；下一个 gate 是独立审查者。
- `FAILED` / `BLOCKED` — final-head CI 到达 terminal non-success；报告
  actual workflow conclusion、affected job(s)、以及 available 时的
  failing / terminated step。
- `COMPLETE` — 仅用于 post-merge 任务：exact merge/main commit 的 CI 为
  terminal SUCCESS。
- `STOP BEFORE MERGE` — 明确的停止点；merge 需要单独授权（契约规则 5）。

## 5. 协议违规

以下行为属于协议违规，必须如实报告：

- 从未经验证的基线开始工作。
- 静默 scope expansion。
- CI 处于 queued / waiting / pending / in_progress 时报告完成。
- 把 agent 自己的报告当作 independent review。
- 未经明确授权移动、重建、amend 或 force-push release history。
