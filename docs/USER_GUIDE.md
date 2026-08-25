# MarketVault 使用说明

本指南是 MarketVault 当前正式版本（v0.7.x）的统一用户操作说明。它描述**当前行为**，不描述版本演进历史；版本历史见 [CHANGELOG.md](../CHANGELOG.md) 与各版本 release 记录。正式契约文档（[contracts/](contracts/)）对精确契约语义保持权威。

## 1. 适用范围

- 覆盖：数据采集（K 线 / 期权 / 交易日历）、审计、Canonical 构建、Dataset 工作流、Sample Generation、Dataset Catalog、Python `ArtifactClient` 读取。
- 描述当前正式 release `v0.7.0` 的行为（安装后可用 `market-vault --version` 确认）。
- 命令名、flag、JSON 字段名、类/函数名、artifact 名一律使用正式英文拼写，不翻译。
- 本指南不复制完整契约条款；需要精确语义时链接到正式契约。

## 2. 环境要求

- Python >= 3.11。
- moomoo OpenD：仅真正通过 OpenD 采集/检查的命令需要本机 OpenD 正在运行、已登录且账号具备所需权限——`collect`、`calendar`、`backfill`、`option-chain`、`option-volatility`、`doctor`。
- 纯本地命令**不需要** OpenD：`inventory`、`audit`、`intraday-audit`、`query`、`calendar-query`，以及 Dataset / Sample Generation / Dataset Catalog 全部命令和 `ArtifactClient`。
- MarketVault Console 默认纯本地；只有界面中明确确认的 Trading Calendar `Fetch from OpenD` 与 Backfill `Execute via OpenD` 操作可能连接 OpenD。
- 操作系统：安装脚本与示例以 Windows PowerShell 为准（`scripts/setup_windows.ps1`、`scripts/first_collection.ps1`）。

## 3. 安装

**PyPI 未发布**，不存在 `pip install market-vault` 的安装路径。请从源码树安装（已验证的 editable install）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

验证安装：

```powershell
market-vault --version
market-vault --help
```

快速初始化与首次采集（可选）：运行 `.\scripts\setup_windows.ps1`；OpenD 就绪后运行 `.\scripts\first_collection.ps1 -TradeDate 2026-07-31`。

## 4. 命令总览

以下全部为当前正式 CLI 命令（`market-vault --help` 可查）。按功能分组：

| 分组 | 命令 | 说明 |
|---|---|---|
| 初始化 / 环境 | `init-catalog` | 创建 DuckDB 元数据表（幂等） |
| | `doctor` | 检查本地 Python / moomoo SDK / OpenD 能力（不写市场数据） |
| 采集（settings-backed） | `collect` | 采集一个已收盘 US 交易日的 K 线 |
| | `calendar` | 从 OpenD 采集历史交易日历 |
| | `backfill` | 按本地交易日历计划并执行可续传的历史回填 |
| | `option-chain` | 采集期权合约静态元数据 |
| | `option-volatility` | 采集期权日度波动率分析 |
| 查询 / 审计（纯本地） | `calendar-query` | 查询本地交易日历 |
| | `query` | 查询 curated K 线 |
| | `inventory` | 汇总本地存储 / 快照 / 覆盖情况 |
| | `audit` | 对照本地交易日历审计交易日覆盖 |
| | `intraday-audit` | 审计最新完整快照的盘中结构 |
| Dataset（settings-independent） | `dataset-build` | 按显式 build-plan 构建一个不可变 Dataset |
| | `dataset-verify` | 校验一个已提交的 Dataset 最终目录 |
| | `dataset-inspect` | 校验并以确定性 JSON 打印 Dataset 内容 |
| Sample Generation（settings-independent） | `sample-generate` | 由显式 generation plan 确定性生成 Dataset build-plan |
| Dataset Catalog（settings-independent） | `dataset-catalog-build` | 从显式 Dataset 构建不可变 Catalog 快照 |
| | `dataset-catalog-verify` | 校验一个 Catalog 快照 |
| | `dataset-catalog-list` | 只读列出快照条目（过滤 + 分页） |
| | `dataset-catalog-show` | 按精确 `dataset_id` 展示一个条目 |

## 5. 配置与 OpenD

顶层选项 `--settings`（默认 `config/settings.yaml`）只对 **settings-backed** 命令生效；Dataset、Sample Generation、Dataset Catalog 命令**忽略**它，也不要求 settings 文件存在。

`config/settings.yaml` 当前结构：

```yaml
opend:
  host: "127.0.0.1"
  port: 11111

storage:
  root_dir: "./data"
  catalog_path: "./catalog/market_vault.duckdb"
  manifest_dir: "./manifests"
  report_dir: "./reports/data_quality"

collector:
  max_count: 1000
  source: "moomoo"
  source_schema_version: "10.9"
  default_session: "ALL"
  default_adjustment: "NONE"
  request_pause_seconds: 0.35
```

要点：

- OpenD 不在默认端点（`127.0.0.1:11111`）时修改 `opend.host` / `opend.port`。
- `collect` / `backfill` / `query` / `audit` / `intraday-audit` 省略 `--session` / `--adjustment` 时，回退到 `collector.default_session`（`ALL`）与 `collector.default_adjustment`（`NONE`）；显式传值覆盖默认值。
- Dataset、Sample Generation、Dataset Catalog 命令与 `ArtifactClient` 是 settings-independent：不读 settings.yaml、不连接 OpenD、不访问网络。

### MarketVault Console v0.1 foundation

Windows 桌面 Console 使用 Python 标准库 Tkinter/ttk，不新增 GUI dependency：

```powershell
python -m market_vault.console --settings config/settings.yaml
```

需要 Python 安装包含可用的 Tcl/Tk runtime（标准 Python.org Windows installer
默认包含）。若 Tcl/Tk 缺失，Console 会以简洁错误退出，不会回退到第三方 GUI 包。

桌面壳层使用左侧导航，提供 Home、Historical Data、Trading Calendar、Market
Data、Inventory、Coverage Audit、Intraday Audit、Runs 与 Storage & Cleanup。
切换工作区不会重建页面，因此现有表单、表格、分页与已审核的清理预览状态会保留。
Home 初始保持被动状态，只有点击 Refresh 后才通过现有 Dashboard backend
读取本地归档概览；打开应用或切换导航不会连接 OpenD。
界面不直接执行 SQL、不打开 DuckDB 内部表、不改写 Parquet，也不提供任意路径
删除；所有业务操作均经过 `ConsoleBackend` 和公开 `MarketVault` API/service。

- Data Explorer、Calendar 和 Runs 使用分页查询；page size 范围为 1..1000。
- 导出仅限当前已加载页面，支持 CSV/JSON，最多 1000 行；不提供无界 Parquet 导出。
- `Plan locally` 不连接 OpenD；`Fetch from OpenD` 和 `Execute via OpenD` 会显示
  host/port 并要求确认。
- GUI 同一时间只运行一个后台操作；错误以状态栏和简洁对话框显示，不向普通用户
  展示异常堆栈。
- Storage / Purge 仅支持先 Preview 再输入 `PURGE <plan_id>`；共置未选择
  symbol 的物理文件会显示 `REFUSED`，不会启用执行。
- 成功执行只把完整 Raw/Curated 文件对移入 `data/quarantine/`，不永久删除，
  不级联修改 Canonical、Dataset 或 Dataset Catalog。

Console 顶部的语言选择器支持 `English`、`简体中文` 和 `日本語`。切换语言时，
左侧导航、Header 与 Home 会即时更新，同时保留当前工作区、输入值、表格与分页。
首次启动
固定使用英语，不读取 Windows 系统区域设置；切换后立即更新现有界面，不重置
当前标签页、表单、分页或已加载结果。Windows 偏好保存在
`%LOCALAPPDATA%\MarketVault\ui-preferences.json`，不写入安装目录、项目配置、
Catalog、manifest 或行情数据。偏好文件缺失、损坏或不可读时会安全回退到英语，
不会阻止访问 MarketVault 数据。

精确行为以 [Console v0.1 contract](contracts/console_v01.md) 为准。

### Windows development EXE build

Windows developers can build the Console as a PyInstaller onedir application.
Install the dedicated build dependency and run the canonical script from any
working directory:

```powershell
python -m pip install -e ".[windows-exe]"
.\scripts\build_windows_console.ps1
```

The development bundle is written to `dist\MarketVault\`, with the editable
settings file at `dist\MarketVault\config\settings.yaml` and supporting native
runtime files under `_internal\`. `MarketVault.exe` resolves this settings file
from its own directory, not the process working directory. The build refuses to
overwrite an existing distributable or ZIP; it never removes a shared `dist`
directory. This is a development artifact, not an official release.

The executable and Tk window use the approved MarketVault Windows icon. To
create a desktop shortcut for an installed onedir bundle, run:

```powershell
.\scripts\install_windows_shortcut.ps1 `
  -ExePath "D:\MarketVault\App\MarketVault\MarketVault.exe"
```

The shortcut targets the complete onedir installation, uses its directory as
the working directory, and takes its icon from `MarketVault.exe`. The installer
refuses a missing executable or an existing shortcut; it does not silently
replace desktop state. Use `-ShortcutPath` to create a shortcut in a separate
test directory instead of the real Desktop.

### Safe Purge v0.1

先生成完全本地的 sealed plan：

```powershell
market-vault --settings config/settings.yaml purge-plan `
  --source moomoo `
  --symbols US.SPY `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --interval 1m `
  --session ALL `
  --adjustment NONE `
  --source-schema-version 10.9
```

仅当计划状态为 `PLANNED` 且没有 refusal reason 时执行：

```powershell
market-vault --settings config/settings.yaml purge-execute `
  --plan-id <plan_id> `
  --confirmation "PURGE <plan_id>"
```

Safe Purge 不连接 OpenD、不接受文件路径、不拆分或重写 Parquet。物理文件中
只要包含请求范围外的 symbol、日期或 request key，整个计划即拒绝。正式规则见
[Safe Purge v0.1 contract](contracts/safe_purge_v01.md)。

## 6. 推荐的数据采集与审计流程

```text
1. init-catalog
2. calendar
3. backfill
4. inventory
5. audit
6. intraday-audit
7. query
```

- `calendar` 与 `backfill`（以及 `collect`、`option-chain`、`option-volatility`）可能连接 OpenD。
- `inventory`、`audit`、`intraday-audit`、`query` 是纯本地读取，永不修改数据、永不触发自动重新采集。

## 7. Historical collection

### collect

采集一个已收盘的 US 交易日（日期必须是已收盘的自然日）：

```powershell
market-vault --settings config/settings.yaml collect `
  --date 2026-07-31 `
  --groups core_universe `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

或直接给代码：

```powershell
market-vault --settings config/settings.yaml collect `
  --date 2026-07-31 `
  --symbols US.MU US.SPY US.QQQ `
  --interval 1m
```

- `--interval` 默认 `1m`；`--session` / `--adjustment` 缺省时回退到 settings 默认值。
- `--groups` 可选 `core_universe`、`trade_universe`、`event_universe`、`option_universe`。
- 每次采集写入新的不可变 Raw / Curated 快照（`batch-<batch_key>-<run_id>.parquet`）；`--force` 重新采集也**不覆盖**更旧的快照。
- 单个 symbol 失败不中断其余 symbol 的采集。

### calendar

从 OpenD 采集历史交易日历：

```powershell
market-vault --settings config/settings.yaml calendar `
  --market US `
  --start-date 2026-01-01 `
  --end-date 2026-12-31
```

或按参考代码：

```powershell
market-vault --settings config/settings.yaml calendar `
  --code US.MU `
  --start-date 2026-01-01 `
  --end-date 2026-12-31
```

查询本地日历（无需 OpenD）：

```powershell
market-vault --settings config/settings.yaml calendar-query `
  --market US `
  --start-date 2026-01-01 `
  --end-date 2026-12-31 `
  --limit 30
```

- 日历数据来自 OpenD `request_trading_days`：历史约 10 年，未来日期限于当前自然年的 12 月 31 日，端点限速约 30 秒最多 30 次请求。
- 返回的日历排除周末与常规节假日，保留 `WHOLE` / `MORNING` / `AFTERNOON` 交易日类型；它不是绝对官方交易所日历，可能不识别全部临时停市。

### backfill

计划并执行一段日期范围的 K 线回填（由本地交易日历驱动，可续传）：

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-market US `
  --start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --symbols US.MU US.SPY US.QQQ `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

或从 universe 组展开：

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-code US.MU `
  --start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --groups core_universe
```

增量模式（从每个 symbol 最新完成日之后继续，即 the first trading date strictly after each symbol's latest completed date；不适用于无历史的新 symbol 时用 `--bootstrap-start-date`）：

```powershell
market-vault --settings config/settings.yaml backfill `
  --calendar-market US `
  --incremental `
  --bootstrap-start-date 2026-01-01 `
  --end-date 2026-07-31 `
  --symbols US.NVDA
```

要点：

- **先收集日历**：日历覆盖必须完整覆盖请求的自然日范围（按自然日检查，不要分块收集造成缺口），否则 `backfill` 拒绝运行并打印缺失日期。
- `--calendar-market` 与 `--calendar-code` 二选一，必须恰好给一个。
- 只接受今天（UTC）之前的日期。
- 重跑同一命令即续传：已完成的 (symbol, trade date) 跳过，只采集失败/缺失项。
- `--incremental` 不能与 `--start-date` 同用；它只从每个 symbol 最新完成日之后继续，不复查更早的中间缺口——中间缺口用显式范围的普通回填补齐（可选 `--force`）。
- `--force` 跳过完成检查、重新采集整个计划范围；与 `--incremental` 组合时起点仍受最新完成日约束。
- 失败项重试 `--max-retries` 次（默认 2），指数退避从 `--retry-backoff-seconds`（默认 2.0，上限 60 秒）开始；失败日期不阻塞其余日期/symbol。
- 每个数据集同一时间只运行一个 backfill 进程。
- 每次回填写入 `manifests/market_bars_backfill_<run_id>.json` 与 `reports/` 下质量报告；manifest 记录每 symbol 的成功/跳过/失败日期、子 run ID、总行数与最终 `status`（`SUCCESS` / `PARTIAL` / `FAILED`）。
- "Completed" 的定义：curated 行存在、run 状态为 `SUCCESS` 或 `PARTIAL`、且无质量检查 `FAIL`；**不校验期望 bar 数**，非空但部分的数据可能被当作已完成。

## 8. Inventory / audit / intraday audit / query

这四个命令均为**纯本地**操作，不连接 OpenD；对已有市场数据（Raw / Curated 等不可变 artifact）**只读**，不会修改数据，也不会自动修复或重新采集——修复缺口永远是显式的 `backfill` 运行。需要生成报告的操作仍会按正式行为写入配置的 `report_dir`（默认 `reports/data_quality/`）。

### inventory

汇总本地 Raw / Curated 文件、快照与行数、参数组合、每 symbol 覆盖日期与完成数：

```powershell
market-vault --settings config/settings.yaml inventory
```

可选过滤：`--symbols` / `--universe` / `--groups`（symbol）、`--start-date` / `--end-date`（交易日）、`--interval` / `--session` / `--adjustment` / `--source-schema-version`（请求键）；`--include-files` 附带物理文件清单。空库报告 `status: EMPTY` 与零计数。

### audit

对照本地交易日历审计交易日覆盖：

```powershell
market-vault --settings config/settings.yaml audit `
  --calendar-market US `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

脚本 / CI 严格模式：

```powershell
market-vault --settings config/settings.yaml audit `
  --calendar-market US `
  --start-date 2026-07-01 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --fail-on-gaps
```

- 期望日期来自本地 `trading_calendar_latest`（绝不来自星期/假日规则）；日历快照的 requested 范围必须完整覆盖请求范围，否则以 `calendar_coverage_gaps` 失败。
- 分类：`COMPLETE`（curated 行与精确请求键匹配、run 状态 `SUCCESS`/`PARTIAL`、无质量 `FAIL`）、`INCOMPLETE`（有行但不满足完成标准，含 `QUALITY_FAIL` / `RUN_FAILED` / `RUN_RUNNING` / `RUN_METADATA_MISMATCH` / `ORPHANED_RUN` / `RUN_STATUS_UNKNOWN` 原因）、`MISSING`（无行）。
- 缺失与不完整日期总是报告；完整日期仅 `--include-complete-dates` 时报告。
- 退出码：`PASS`=0，`WARN`=0（`--fail-on-gaps` 时 2），`FAILED`=1。

### intraday-audit

校验范围内每个 (symbol, trade date) 的**最新完整物理快照**的盘中结构（绝不使用去重视图 `market_bars`）：

```powershell
market-vault --settings config/settings.yaml intraday-audit `
  --calendar-market US `
  --start-date 2026-07-30 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --interval 1m `
  --session ALL `
  --adjustment NONE
```

严格模式（WARN 退出 2）：

```powershell
market-vault --settings config/settings.yaml intraday-audit `
  --calendar-market US `
  --start-date 2026-07-30 `
  --end-date 2026-07-31 `
  --symbols US.MU `
  --fail-on-warn
```

- 校验：请求元数据、时间戳有效性、UTC / 市场时钟一致性、`market_calendar_date` 一致性、session 标签（`OVERNIGHT` / `PRE_MARKET` / `REGULAR` / `AFTER_HOURS`）、重复 bar、分钟边界对齐、间隔网格、连续观察段内部缺口。
- 内部缺口只报 `WARN`（不 `FAIL`）：停牌、熔断、无成交时段可以合法地产生空 bar。
- 不评估：段首/段尾覆盖（session boundary coverage）、整段缺失的 session、固定日 bar 数（无 1440/390/1201 硬编码）、提前收盘。
- 该限制的 OpenD/SDK 证据和最小安全后续设计见
  [Intraday Boundary Schedule Evidence](intraday_boundary_schedule_evidence.md)。在获得可覆盖
  `Session.ALL` 的权威逐日时段表之前，不能用已观察 K 线、`trade_date_type` 或静态交易时间推断边界完整性。

### query

查询 curated K 线（从去重视图 `market_bars` 读取，`--adjustment` 默认 `NONE`）：

```powershell
market-vault --settings config/settings.yaml query `
  --code US.MU `
  --trade-date 2026-07-31 `
  --interval 1m `
  --session REGULAR
```

## 9. Option data

### option-chain

采集某 underlying 在到期日范围内的静态合约元数据：

```powershell
market-vault --settings config/settings.yaml option-chain `
  --underlying US.MU `
  --start-date 2026-08-07 `
  --end-date 2026-09-18 `
  --option-type ALL `
  --option-cond-type ALL
```

- `--option-cond-type` 仅支持官方 moomoo option-chain API 暴露的过滤：`ALL`、`ITM`（映射 `OptionCondType.WITHIN`）、`OTM`（映射 `OptionCondType.OUTSIDE`）；API 没有 ATM 过滤。
- 端点单次请求最多 30 天跨度；MarketVault 自动把更长范围切成不重叠的 30 天块并合并为一个 raw 文件、一个 curated 文件、一个 manifest、一个质量报告。
- curated 数据集标准化 `option_code`、`option_name`、`underlying_code`、`option_type`、`strike_price`、`expiry_date`、`contract_size`、`lot_size`、`exchange`、`exercise_type`、`suspension`、`delisting`、`captured_at`、`source`、`source_schema_version`、`ingestion_run_id`；moomoo 未返回的字段保留为 null，不推断。

### option-volatility

采集一个或多个期权代码的日度波动率分析：

```powershell
market-vault --settings config/settings.yaml option-volatility `
  --codes US.MU260807C120000 US.MU260807P100000 `
  --start-date 2026-07-01 `
  --end-date 2026-07-31
```

- 官方端点接受 lookback 周期而非直接起止日期；MarketVault 选择从采集日覆盖请求起点的最小官方周期（`WEEK` / `MONTH` / `QUARTER` / `HALF_YEAR` / `YEAR`），再过滤到请求日期范围。
- 早于最大 `YEAR` 周期的请求在调用 OpenD 之前被拒绝。
- 覆盖检查使用工作日边界启发式，不识别 NYSE / Nasdaq 节假日。

## 10. Canonical builds

- **目的**：把审计为 `COMPLETE` 的不可变快照派生成不可变、可验证的 Canonical 构建物，作为 Dataset 的正式输入。Canonical 只从审计为 COMPLETE 的键派生行；`INCOMPLETE` / `MISSING` 键从不产生 Canonical 行；没有合格 COMPLETE 快照的请求产生确定性 EMPTY 构建（完成状态不会被转成合成行或 gap 副作用条目）。
- **路径**：audited COMPLETE 快照 → Canonical 构建（`market_vault.canonical` 的构建器与 materialization Python API）→ 提交的 Canonical 最终构建目录 → 正式验证读取器。
- **读取**：唯一公开读取路径是严格验证读取器 `load_verified_canonical_build`（或 `ArtifactClient.load_canonical_build`），任何不一致都 fail closed。
- 当前**没有 Canonical CLI 命令**；Canonical 构建走 Python API，CLI 侧由 Dataset / Sample Generation / Catalog 命令作为显式输入消费。
- bar 携带三个时钟：`event_time`（UTC）、`market_available_at`（事件时间 + 名义间隔，市场时钟）、`archive_available_at`（`run_finished_at`，归档时钟）；可选 `dataset_as_of` 提供归档时间复现。

## 11. Dataset workflow

Dataset 命令完全离线：不加载 settings.yaml、不连接 OpenD、不访问网络、不做任何 `latest` 扫描或 Canonical 自动选择。`dataset-build` 只接受 `--plan`，每个正式输入（Canonical 最终目录、FeatureSpec / LabelSpec 文件、requests、scope、split spec、可选 `dataset_as_of`、`output_root`）都必须在版本化 build-plan JSON（`market-vault-dataset-build-plan-v1`）中显式声明；计划内相对路径锚定到计划文件所在目录。

```powershell
$complete = market-vault dataset-build --plan "D:\work\market-vault-dataset-example\complete.plan.json" | ConvertFrom-Json

market-vault dataset-verify --build-dir $complete.build_path
market-vault dataset-inspect --build-dir $complete.build_path --offset 0 --limit 20
```

- `dataset-verify` / `dataset-inspect` 需要**最终 Dataset 目录** `<output_root>/<dataset_id>`，不是 `output_root` 本身；二者严格只读。
- 最终目录名是确定性 `dataset_id`（而非时间戳）；原子物化：同文件系统 staging、`_SUCCESS` 最后写入、no-overwrite rename；已有冲突目录 fail closed 绝不覆盖；相同构建幂等返回 `created_new_build = false` 且不重写任何文件。
- `dataset-inspect` 额外打印 scope、schema、spec 固定信息、split spec 与诊断、build report，以及按 `--offset` / `--limit` 切片（`--limit` 上限 1000）的确定性 JSON 行。
- `dataset_status = EMPTY`（`requests: []`）是**设计结果**，不是失败；EMPTY 构建仍物化合法的零行 Parquet、manifest、build report、spec artifacts 与 `_SUCCESS`，并通过 verify / inspect（deterministic EMPTY build：当 no eligible COMPLETE snapshots 时，EMPTY 绝不产生 synthetic rows，也不会被转成 internal-gap sidecar entries）。
- gap sidecar 只记录 internal nominal-spacing gaps，**从不**推断段首/段尾/session 缺口（never infers leading/trailing/session gaps）。
- COMPLETE 不保证：只有验证读取器从实际输入证明满足 Feature lookback、Label horizon、同交易日、split/purge 等条件时才 COMPLETE。
- 完整示例包（FeatureSpec / LabelSpec / split-spec 文件、COMPLETE 与 EMPTY 计划模板、stdlib-only 渲染器、Windows PowerShell 全流程、24 项常见错误）见 [examples/dataset_cli/README.md](../examples/dataset_cli/README.md)。

**Dataset 策略边界**（policy boundaries）：当前 PIT / Dataset policy 仅支持 `adjustment = NONE`（不做复权）；adjusted-price 的 corporate-action as-of / PIT reconstruction 尚未实现，adjusted requests 会 fail closed。Feature window 按正式 PIT contract 的半开时间窗（half-open `[feature_window_start, feature_window_close)`）以及 market / archive availability 规则处理，不受 anchor-market-calendar-date 限制。默认的 no-cross-trading-day policy 作用于 Label：每个 Label row 必须属于该 sample 的 `anchor_market_calendar_date`。Dataset 是只读数据产物，不执行 arbitrary user code；所有读取走 verified Dataset reader（严格验证读取器）与 immutable Dataset materialization（不可变物化），任何不一致都 fail closed。

## 12. Sample Generation

```powershell
market-vault sample-generate --plan <PATH>
```

- 从显式 generation plan 生成确定性 PITSampleRequest 序列，输出为普通 `market-vault-dataset-build-plan-v1` 文档，可直接交给 `dataset-build`（生成输出是 Dataset build-plan 的正式输入）。
- 只通过正式验证读取器读取 verified Canonical 构建，并使用计划中显式固定的 Feature / Label / split 输入。
- `sample-generate` 自身**不**构建 Dataset、**不**执行 PIT 装配或任何 Feature / Label 值计算，**绝不**声称样本 COMPLETE。
- 不使用当前时间、不做 `latest` 发现、不读 settings.yaml、不连接 OpenD、不访问网络。

## 13. Dataset Catalog

```powershell
# 构建（--dataset-root 与可重复的 --candidate-build-dir 互斥）
market-vault dataset-catalog-build `
  --dataset-root "D:\data\datasets" `
  --output-root "D:\data\catalog" `
  --built-at "2026-08-09T12:00:00+00:00"

# 校验
market-vault dataset-catalog-verify --snapshot-dir "D:\data\catalog\<snapshot_id>"

# 只读发现（过滤 + 分页）
market-vault dataset-catalog-list `
  --snapshot-dir "D:\data\catalog\<snapshot_id>" `
  --status COMPLETE `
  --symbol US.MU `
  --offset 0 --limit 20

# 按精确 dataset_id 展示
market-vault dataset-catalog-show `
  --snapshot-dir "D:\data\catalog\<snapshot_id>" `
  --dataset-id "<64 位小写 hex>"
```

- **构建**：从 verified 不可变 Dataset 集合投影为确定性 Catalog 内容身份与不可变物理快照（`catalog.json` / `manifest.json` / `_SUCCESS`），原子、no-replace 发布。`--dataset-root` 只扫描直接 64-hex 子目录作为候选；`--built-at` 必须为带时区的 ISO 8601——**绝不使用当前时间**。
- **校验**：验证读取器从快照自身字节重算全部内容与物理身份，绝不重新加载或改写记录的 Dataset 位置；任何不一致 fail closed。
- **发现**：`dataset-catalog-list`（只读过滤：`--status` / `--dataset-kind` / `--symbol` / `--trade-date` / `--interval` / `--adjustment` / `--requested-session` + `--offset` / `--limit`，上限 1000）与 `dataset-catalog-show` 是正式查询面；**没有**独立的 `dataset-catalog-query`。
- 没有修复、没有 `latest` 指针、没有 Dataset 重写：Catalog 从不修改任何 Dataset 或 Canonical artifact。

## 14. Python ArtifactClient

settings-independent、只读的 Python artifact 客户端。当前正式公开面（恰好这三个方法）：

```python
ArtifactClient()
ArtifactClient.load_canonical_build(build_dir)
ArtifactClient.load_dataset(build_dir)
ArtifactClient.load_dataset_catalog(snapshot_dir)
```

示例：

```python
from pathlib import Path
from market_vault import ArtifactClient

client = ArtifactClient()

canonical = client.load_canonical_build(
    Path(r"D:\data\canonical\dataset=market_bars_canonical\<canonical_build_id>")
)
print(canonical.canonical_build_id, canonical.status, len(canonical.bars))

dataset = client.load_dataset(Path(r"D:\data\datasets\<dataset_id>"))
print(dataset.dataset_id, dataset.status, len(dataset.rows))

catalog = client.load_dataset_catalog(Path(r"D:\data\catalog\<snapshot_id>"))
print(catalog.snapshot_id, catalog.dataset_count)
```

要点：

- **显式最终路径**：每个读取都传入确切的最终 artifact 目录（Canonical 最终构建目录 / `<output_root>/<dataset_id>` / `<output_root>/<snapshot_id>`），绝不传父目录或 `latest` 路径；没有自动发现、没有 settings / 环境变量 / cwd 推导。
- **验证读取器委托**：`load_canonical_build` → `load_verified_canonical_build`、`load_dataset` → `load_verified_dataset`、`load_dataset_catalog` → `load_verified_dataset_catalog`，返回正式验证对象（`VerifiedCanonicalBuild` / `VerifiedDatasetBuild` / `VerifiedDatasetCatalogSnapshot`）；无客户端解析、无第二信任路径、无异常包装。
- **只读**：无写入、无修复、无删除；artifact 不可变，消费代码也不得改写 artifact 文件。
- **无 latest / settings / 网络 / 当前时间**：构造器零参数、无文件系统访问。
- **轻量 import**：`import market_vault` 不导入 duckdb / pandas / moomoo / futu；读取器导入发生在实际方法调用边界。
- **错误**：即正式验证器错误类——`CanonicalArtifactValidationError` / `DatasetArtifactValidationError` / `DatasetCatalogArtifactValidationError`；损坏 artifact、错误目录布局、symlink/junction 路径、意外文件、篡改身份一律 fail closed。

详细指南：[v0_7_0_python_client_usage.md](v0_7_0_python_client_usage.md)；正式契约：[contracts/python_client.md](contracts/python_client.md)；源码树示例：[examples/python_client/](../examples/python_client/README.md)。

## 15. Artifact / path rules

- **output root**：数据根目录（settings `storage.root_dir`，默认 `./data`；Dataset 计划中的 `output_root` 类似）只承载最终目录，**不是**读取/验证目标。
- **final artifact / build / snapshot directory**：真正的读取目标：
  - Dataset：`<output_root>/<dataset_id>`（目录名即确定性 `dataset_id`）；
  - Canonical：`.../canonical/dataset=market_bars_canonical/<canonical_build_id>`；
  - Dataset Catalog 快照：`<output_root>/<snapshot_id>`（恰好是 64-hex `snapshot_id`）。
- 一律显式传最终目录；把 `output_root` 或父目录传给验证器 / `ArtifactClient` 会 fail closed。**不存在 `latest` 自动发现**（no `latest` auto-discovery）。
- **不可变期望**：Raw / Curated 快照按 run 写入（`batch-<batch_key>-<run_id>.parquet`），`--force` 不覆盖旧快照；Dataset / Catalog 原子物化、`_SUCCESS` 最后写入、冲突目录不覆盖；任何验证 / 读取都**不**修复或改写 artifact。

## 16. Exit codes and stdout/stderr

按命令家族分别说明，不做跨家族推广：

- **Dataset / Sample Generation / Dataset Catalog 家族**（实现与正式文档共同证明）：`0` = 成功；`1` = 文档化的命令失败；`2` = argparse 用法错误。成功输出恰好一个 JSON 对象到 **stdout**（stderr 保持为空）；文档化失败恰好一个 JSON 对象到 **stderr**（stdout 保持为空）；argparse 诊断到 stderr。解析成功 JSON 只从 stdout 取。
- **`audit`**（settings-backed 家族的正式文档化行为，仅该命令）：`PASS` 退出 0；`WARN` 退出 0（`--fail-on-gaps` 时 2）；`FAILED` 退出 1。`intraday-audit` 同族：`--fail-on-warn` 时 `WARN` 退出 2。
- 其他命令各自的退出码以当前实现与正式文档为准，不要假设与本指南任何条目相同。

## 17. Common problems

1. **把 `output_root` 当成最终目录** — `dataset-verify` / `dataset-inspect` / `ArtifactClient` 收到根目录会 fail closed。应传 `<output_root>/<dataset_id>`（或 Canonical / Catalog 最终目录）。
2. **OpenD 不可用 / 未登录** — 采集类命令失败。先运行 `doctor` 检查 Python、SDK、OpenD host/port 与 socket 连通性。
3. **账户权限 / 历史额度不足** — 权限或配额失败按请求记录在 run manifest；先确认账号具有所需市场数据权限与历史额度。
4. **未验证 / 损坏的 artifact** — 验证读取器抛正式验证错误，绝不返回部分结果。正确做法：重新构建或改指向，**绝不**"修复" artifact 或绕过验证读取器。
5. **使用 `latest` / 自动发现** — 不存在也不支持。所有输入必须是显式最终路径。
6. **Canonical 覆盖不完整** — COMPLETE 不保证；Feature lookback 或 Label horizon 覆盖不足时样本被排除或标签为 `INCOMPLETE`。扩展 Canonical 覆盖或调整窗口。
7. **settings 混淆** — `--settings` 只对 settings-backed 命令生效；Dataset / Sample Generation / Dataset Catalog 命令忽略它，也不需要 settings 文件存在。
8. **backfill 前未收集 calendar 或日历有缺口** — `backfill` 拒绝运行并打印缺失日期。一次性覆盖整个自然日范围（分块收集会产生覆盖缺口）。
9. **并发 backfill** — 每个数据集同时只运行一个 backfill 进程，否则可能重复采集相同项。
10. **`--limit` 超过 1000** — argparse 拒绝（退出码 2）。用 `--offset` / `--limit`（≤1000）分页。
11. **把 EMPTY 当失败** — `dataset_status = EMPTY`（`logical_row_count = 0`）是 `requests: []` 的设计结果，仍可验证，不是失败。
12. **时区缺失的 datetime** — build-plan / generation-plan / catalog 的 `built_at`（与 `dataset_as_of`）必须为带时区 ISO 8601，否则严格解析拒绝。

## 18. Data capability boundaries

- **历史可回填**：K 线、期权合约静态元数据、日度波动率分析——在 OpenD 与账户权限允许的范围内。
- **历史不可重建**：分钟级 Bid/Ask、订单簿深度（order-book depth）、Greeks、完整盘中 IV——若从未实时捕获，事后无法重建（cannot be reconstructed after the fact）；这些字段需要实时捕获与订阅管线。
- **产品不支持**：实时订阅、实时 Bid/Ask / Greeks、持仓、信号（signals）、执行、自动交易（automatic trading）。
- **产品不支持**：ML 训练（ML training）、模型评估、回测框架（backtest）、特征重要性——MarketVault 只生产可验证的数据与 Dataset 产物，ML 训练与模型评估是用户自己的下游工作。
- `ArtifactClient` 严格只读；验证读取没有 `latest` 自动发现。

## 19. Further documentation

- 版本历史：[CHANGELOG.md](../CHANGELOG.md)
- 正式 v0.7.0 release 记录：[release_v0_7_0.md](release_v0_7_0.md)
- 正式契约：[contracts/](contracts/)（含 [python_client.md](contracts/python_client.md)、[dataset_cli.md](contracts/dataset_cli.md)、[sample_generation.md](contracts/sample_generation.md)、[dataset_catalog.md](contracts/dataset_catalog.md)）
- Dataset CLI 完整示例：[examples/dataset_cli/README.md](../examples/dataset_cli/README.md)
- Python Client 详细指南：[v0_7_0_python_client_usage.md](v0_7_0_python_client_usage.md)
- Python Client 源码树示例：[examples/python_client/README.md](../examples/python_client/README.md)
- 开发 / 治理：[governance/](governance/)（DEVELOPMENT_PLAYBOOK / RELEASE_PLAYBOOK / AGENT_HANDOFF）
