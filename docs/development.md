# TickWitness 开发入口

状态：Sprint 4 证据闭环，2026-10-26。已接受的数据/声明/受限回放之上新增v2可执行协议、per-protocol attempt预算、独立账务/费用/最后bid估值、导出与离线核验。完整操作见[证据工作流](evidence-workflow.md)。v1仍不可执行，首个profile仅EUR/USD内置买单；任意源码、确认解封、搜索判定和完整公共SDK尚未提供。

## 从干净 checkout 开始

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 的0.12.13版本；当前项目约束为 `>=0.12.13,<0.13`，CI固定0.12.13。项目支持范围暂定Python3.12–3.14，默认`.python-version`为3.12。完整跨平台验收以PR的CI结果为准，不把纯核心包检查当成第三方引擎支持认证。

```sh
git clone https://github.com/Darrenus/tickwitness.git
cd tickwitness
make sync
make check
make build
```

PR#73–76已合并；本批验收前位于`codex/sprint-04-evidence-workflow`。`make sync`使用已提交的`uv.lock`，不静默更新版本；修改依赖时显式运行`uv lock`，把版本与锁文件一同提交。核心运行时无第三方依赖，开发工具在`dev`组；`nautilus`是显式可选extra，不能成为domain隐式依赖。

`make build`先同步锁定的开发工具，再使用该环境中的固定Hatchling构建wheel/sdist，不使用未固定的全局构建后端。`dist/`不提交Git。当前`0.0.2.dev0`是内部开发构建，不是S4的0.1产品预览，没有上传PyPI。目录可能保留以前版本的wheel，本地安装应选择明确版本文件；CI始于干净checkout。

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

原生adapter的声明支持输入/决策/订单/成交/账户trace，拒绝checkpoint。能力声明不等于当前环境已安装依赖；运行时还核对精确版本、输入profile和结果绑定。完整native检查使用：

```sh
uv sync --locked --extra nautilus
uv run --locked --extra nautilus pytest
```

`uv sync`默认只同步核心，会移除不需要的可选包；原生操作持续显式传`--extra nautilus`。预检、比较与原有数据/协议路径无需安装native。

## CI与打包边界

`Engineering`工作流执行同一Make入口，核心矩阵为Ubuntu24.04/macOS15与Python3.12/3.13/3.14；缺native时显式跳过原生case，不把skip当引擎通过。独立native矩阵为Ubuntu24.04/macOS26的Python3.12，安装固定extra运行全部测试，再用wheel替换editable包，以独立目录、Python`-I`验证真实worker/CLI。聚合engineering检查要求native矩阵也通过。

固定Nautilus wheel的macOS标签是`macosx_26_0_arm64`，不能在macOS15当作受支持binary安装；原生CI初次使用macOS15时因退回上游sdist构建而失败。项目uv配置明确`no-build-package=["nautilus-trader"]`，缺兼容wheel立即拒绝，避免用户意外进入未验证的Rust/Cython源码构建。核心包不受此native平台限制；[runner平台说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

distribution作业从sdist构建wheel，在新环境/不同目录离线安装，验证原有数据与协议链路及核心安装下明确的engine_unavailable；native作业则验证真正L2部分成交与监督进程输出。源码包包含原创examples供测试，wheel不包含native二进制或第三方源码。

`scripts/smoke_evidence.py`另验完整v2链路：原生安装实跑freeze/run/export/move/verify并故意破坏对象；核心安装核对缺依赖的attempt被消费，并独立验证随附的native生成样例。纯核心回归禁止verifier导入Nautilus或连接SQLite。费用double-quantization与模糊cent候选也有独立原生完整回放CI案例，不靠宽容差放过账务矛盾。

历史spike保留原证据，不由正式adapter覆盖。S3的[十次基线](research/sprint-03-replay-baseline.md)保存原始耗时与安装制品/模块hash，不冒充纯撮合吞吐。第三方引擎的许可证、平台和支持语义分别登记；原始交易数据及私有策略不进入公开仓库。

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
