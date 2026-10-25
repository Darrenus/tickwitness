# TickWitness 开发入口

状态：Sprint 2 冻结协议工程，2026-10-26。当前支持有界JSONL数据导入、完整性inspection、绑定真实数据与策略源码的声明冻结、开发集读取和确认集拒绝。回放、反例搜索和最终研究判定尚未实现。[选型记录](research/engine-selection.md)提出NautilusTrader1.231.0作为有限L2集成目标；第三方引擎当前仍只用于独立spike，没有正式adapter。

## 从干净 checkout 开始

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 的0.12.13版本；当前项目约束为 `>=0.12.13,<0.13`，CI固定0.12.13。项目支持范围暂定Python3.12–3.14，默认`.python-version`为3.12。完整跨平台验收以PR的CI结果为准，不把纯核心包检查当成第三方引擎支持认证。

```sh
git clone https://github.com/Darrenus/tickwitness.git
cd tickwitness
make sync
make check
make build
```

Sprint1基础与PR#74的数据导入已合并；本批冻结能力验收前位于`codex/sprint-02-frozen-protocols`。`make sync`使用已提交的`uv.lock`，不静默更新版本；修改依赖时显式运行`uv lock`，把版本与锁文件一同提交。根包运行时没有第三方依赖，开发工具在`dev`依赖组。HftBacktest/Nautilus不能成为纯domain的隐式依赖。

`make build`先同步锁定的开发工具，再使用该环境中的固定Hatchling构建wheel/sdist，不使用未固定的全局构建后端。`dist/`不提交Git。当前版本`0.0.1.dev0`是内部开发基础，不是S4的0.1产品预览，也没有上传PyPI。

## 当前检查

| 命令 | 检查范围 |
| --- | --- |
| `make lint` | `src/`、`tests/`、`scripts/`的Ruff规则 |
| `make format` | 同范围格式检查 |
| `make type` | `src/`严格mypy检查 |
| `make test` | 域能力/数据/协议合同、真实FS/SQLite与协议CAS发布和破坏路径、应用绑定与访问政策、CLI；不运行外部引擎或访问交易所 |
| `make docs` | 本地文档链接、故事ID与Sprint预算 |
| `make check` | 上述所有检查，失败返回非零 |
| `make build` | 使用锁定开发环境构建可安装wheel与源码包 |

安装入口提供帮助、版本，以及[数据导入](data-import.md)与[研究协议](research-protocols.md)所列用例：

```sh
uv run --locked tickwitness --help
uv run --locked tickwitness --version
```

回放尚未实现。能力声明类型只检查请求集合是否被声明支持，不认证引擎真实性；每个adapter还需要S3契约测试。

## CI与打包边界

`Engineering`工作流执行同一Make入口，核心测试矩阵为Ubuntu24.04/macOS15与Python3.12/3.13/3.14。独立distribution作业从sdist构建wheel，在新环境、不同工作目录离线安装wheel，实际验证数据import/inspect、未知时间、篡改失败，以及协议freeze/inspect、幂等、开发集读取、确认集拒绝，另检查命令和domain导入，防止源码路径掩盖打包问题。

研究spike各有固定依赖、命令与证据，不属于根包的正式adapter或基础单测。禁止把其需要的所有金融依赖塞入开发包；第三方引擎的许可证、平台和支持语义分别登记。原始交易数据和任何私有策略不进入公开代码仓库。

## 受限本地环境的排错记录

当前机器macOS27/arm64、CPython3.12.14。本次发现项目`.venv`中的`.pth`文件带有`UF_HIDDEN`属性，CPython会跳过它们，导致editable安装元数据存在而`import tickwitness`失败；独立wheel安装不受该问题影响。诊断中`python -v`明确输出`Skipping hidden .pth file`，因此没有用`PYTHONPATH=src`掩盖安装故障。

仅当出现相同诊断时，检查自己新建虚拟环境的文件属性，并对该环境中对应文件执行：

```sh
ls -lO .venv/lib/python3.12/site-packages/*.pth
chflags nohidden .venv/lib/python3.12/site-packages/_editable_impl_tickwitness.pth
chflags nohidden .venv/lib/python3.12/site-packages/_virtualenv.pth
make check
```

本次环境中隐藏属性会再次出现，因此最终本地验收使用了位于工作区外的专用临时环境；wheel安装也在独立临时目录验证。遇到相同情况时可使用uv原生环境覆盖，不需要改源码路径：

```sh
UV_CACHE_DIR=/private/tmp/tickwitness-uv-cache UV_PROJECT_ENVIRONMENT=/private/tmp/tickwitness-core-env make sync
UV_CACHE_DIR=/private/tmp/tickwitness-uv-cache UV_PROJECT_ENVIRONMENT=/private/tmp/tickwitness-core-env make check
```

不要对全盘、其他项目或全局Python执行递归属性修改。以上只影响当前命令和本项目专用临时环境，不改变依赖来源或用户全局配置，也不使用`PYTHONPATH=src`绕过安装验证。
