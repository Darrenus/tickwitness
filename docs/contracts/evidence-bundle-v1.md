# Evidence Bundle v1

状态：S4 目录 IO 契约。bundle 把一次 development replay 的固定证据字节迁移到另一个目录；IO 层只核验结构、预算与内容哈希。应用层另行重建数据、协议、账务评价和 attempt 绑定。**文件完整不等于 native 已重新执行、作者身份可信或研究命题获得认证。**

实现见 [evidence_bundles.py](../../src/tickwitness/infrastructure/evidence_bundles.py)，实际文件系统回归见 [test_evidence_bundles.py](../../tests/infrastructure/test_evidence_bundles.py)。数据契约为 [Normalized Events v1](normalized-events-v1.md)，资格回放边界见 [S3 原始基线](../research/sprint-03-replay-baseline.md)。

## 1. 固定目录与身份

```text
<bundle-root>/
  manifest.json
  objects/
    sha256/
      <64-character lowercase SHA-256>
      ...
```

不使用 tar、zip、pickle、动态插件、用户路径列表或恢复脚本。最终目录只允许上述固定三层；未知文件、额外目录、`.DS_Store` 等隐藏条目同样拒绝。文件名只来自已验证的小写 SHA-256，不解析任意 `ref` 路径。

manifest 必须是非空、精确 canonical UTF-8 JSON：key 排序、紧凑分隔符、`ensure_ascii=False`、无 BOM、重复 key、float、NaN/Infinity、尾随换行或未知字段。以下代码只展示结构；`<digest>` 是占位，不能直接作为合法 fixture：

```json
{
  "kind": "evidence_bundle_v1",
  "schema_version": 1,
  "scope": "development_replay_v1",
  "roles": {
    "protocol": {
      "sha256": "<digest>",
      "size_bytes": 123,
      "ref": "objects/sha256/<digest>"
    }
  }
}
```

真实 `roles` 必须恰好有下表八项，每项恰好含 `sha256`、`size_bytes`、`ref`。hash 必须是 64 字符小写 hexadecimal；size 必须是真正的正整数，boolean 不能冒充 integer；ref 必须逐字节等于 `objects/sha256/` 加该 hash。同一 hash 不允许声明不同 size。

`bundle_id = SHA256(manifest canonical bytes)`。manifest 没有创建时间、原始绝对路径、作者签名或自引用 bundle ID。完全相同的八份字节在不同目录产生相同身份；完全重写内容并重算全部 hash 会产生另一份 bundle，不能只靠目录名称或自算 hash 证明原作者身份。需要 pinned bundle identity 的调用者必须另外比较预期 ID。

## 2. 八个 role 与预算

| role | 本层字节上限 | 应用层解释 |
| --- | ---: | --- |
| `protocol` | 128 KiB | executable development protocol 的 canonical bytes |
| `dataset_manifest` | 64 KiB | development dataset 的内容 manifest |
| `raw` | 8 MiB | 绑定的 development 原始输入 |
| `normalized` | 8 MiB | 规范化 development 事件 |
| `report` | 4 MiB | 数据质量报告 |
| `replay_result` | 16 MiB | replay qualification 结果 |
| `evaluation` | 4 MiB | 应用封装的命题 observation 与精确账务评价 |
| `attempt` | 256 KiB | 协议、reservation/attempt 与 data/spec/result/evaluation hash 的绑定回执 |

这些是 IO 预算，不能放宽 domain loader 自己的更小预算。例如内部 ReplayEvaluation 仍须满足它自己的 64 KiB 契约。所有 role 都要求非空 immutable `bytes`；bytearray、文本字符串和空字节拒绝。IO 层不把 role 内容当作 Python 执行，也不因 role 名称就认定其业务含义正确。

读取默认 `BundleLimits(max_total_bytes=64 MiB, max_files=32, max_manifest_bytes=64 KiB)`。total 包括 manifest 与每个唯一 CAS 对象的实际字节；file count 包括 manifest 和唯一 CAS 对象，不计固定目录。相同内容跨 role 共享一个对象。调用者可设更严格的正整数预算；超额声明在读取对象前拒绝，实际文件也须与声明 size 完全一致，不能利用小 size 声明加载大文件。

确认集 observations 不属于八个 role。应用导出必须验证这里只含 protocol 绑定的 development 数据；confirmation dataset ID 只作为协议内的外部声明引用保留，离线包不证明该外部对象存在、无重叠、未曾泄露或通过审核。固定 role 名称本身不能替代这项应用校验。

## 3. Python API 与不可变输出

```python
export_bundle(destination: Path, artifacts: Mapping[str, bytes]) -> ArtifactBundle
read_bundle(root: Path, *, limits: BundleLimits = BundleLimits()) -> ArtifactBundle
```

`ArtifactBundle` 是 frozen dataclass，保存 immutable manifest bytes 与 immutable `(role, bytes)` tuple；直接构造也要校验八个 role、预算、hash/size 闭包，不能用 bytearray 包装一份看似冻结的证据。公开属性：

- `bundle_id`：由 manifest bytes 派生。
- `manifest_bytes`：精确 canonical bytes。
- `manifest`：每次独立解码的新字典。
- `artifacts`：每次返回新的 `dict[str, bytes]`；字节本身不可变。

修改输入 mapping、返回的 manifest 嵌套字典或 artifacts 字典不会改变已构造 bundle。没有供 worker 使用的数据库句柄，也没有网络、引擎回放或 arbitrary source 参数。

## 4. 导出的提交边界

destination 的 **parent 必须已存在**，由 owner 明确选择并负责信任；本层不做 `mkdir -p`。destination 必须不存在，既有空目录、非空目录、普通文件、符号链接或同内容 bundle 都拒绝，不覆盖、不删除用户目标。需要再次导出时选择新的 destination。

发布顺序：

1. 在任何目录写入前校验全部 payload、固定 role、各项预算和完整 manifest。
2. 在已打开的 parent directory fd 下，以随机名字创建权限 0700 的私有 sibling stage。
3. 写唯一 CAS 对象、逐项校验字节并 fsync；同步固定对象目录。
4. 最后写、校验并 fsync `manifest.json`，再同步 stage 目录。
5. 以原子 **no-replace rename** 将完整 stage 发布成 destination；此 rename 是最终目录可见的提交点，然后 fsync parent。

no-replace 采用标准库 ctypes 的窄 OS 接口：Linux `renameat2(RENAME_NOREPLACE=1)`，macOS `renameatx_np(RENAME_EXCL=4)`。函数原型与常量依据 [Apple XNU 头文件](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h)、[Linux UAPI 头文件](https://github.com/torvalds/linux/blob/master/include/uapi/linux/fs.h)；拒绝覆盖的行为见 [Linux 文件系统接口](https://github.com/torvalds/linux/blob/master/Documentation/filesystems/vfs.rst)。缺少接口、不支持的系统/文件系统或相应 errno 均报错，**不降级成会替换空目录的普通 rename**。目前实现路径覆盖 Linux/macOS；单机测试不能代替所有文件系统认证。

对象写入、manifest 写入或 rename 前的 fsync 失败时，destination 不会出现可用 manifest；失败 stage 尽力清理，清理本身若失败可能留下 owner 私有的未提交 sibling，不能把它当作已发布目标。两个并发 exporter 争同一 destination 时只有一个可提交。

rename 之后如果 parent fsync 失败，完整目标已经可见，但断电持久性尚未确认。本层抛 `BundleDurabilityError`，保留目录，调用者应 read/verify 后人工决定下一步；不能把它描述为“目标不存在，所以可安全覆盖重试”。本层不删除已发布目标，也不声称做过真实断电恢复实验。

## 5. 读取与安全边界

读取只打开固定目录和对象，不写文件、不创建缺失根、不连接网络、不调用 SQLite 或 native replay engine。根不存在为 `BundleNotFoundError`；已存在但缺 manifest、缺对象或树不完整为 `BundleError`。

每个被打开的目录和文件使用目录 fd 与 `O_NOFOLLOW`；文件使用 nonblocking open，fstat 必须为 regular file，FIFO 不等待 writer。完整枚举三个固定层级，拒绝全部未知/额外条目及符号链接，包括指向树外的隐藏符号链接。读取时先核 size/预算，随后核完整 SHA-256；返回的字节与 manifest 引用必须闭合。移动完整目录后可独立读取，不依赖原始本机绝对路径、catalog 或 native 安装。

parent/root 祖先是可信 owner 配置边界；root 本身及其下条目拒绝 symlink。这里不隐藏文件于宿主 owner，也不承诺抵御恶意 owner 并发替换祖先、挂载点或正在读取的普通文件。硬链接身份、文件系统远端故障和真实来源真实性没有获得新的安全认证。

错误分类：

| exception | 含义 |
| --- | --- |
| `BundleNotFoundError` | 缺失 root，读取没有创建它 |
| `BundleDestinationExistsError` | 目标已存在或发布竞争失败，未替换它 |
| `BundleDurabilityError` | 完整目标已发布，但 parent fsync 未确认断电持久性 |
| 其他 `BundleError` | schema、预算、hash、树结构、安全打开、平台或普通 IO 失败 |

## 6. 离线语义验证仍由应用完成

应用必须加载并重建 executable protocol、dataset manifest、normalized events/report、ReplayResult、账务评价和 RunReceipt，逐项校验内容身份与来源账务。IO 层的 `ArtifactBundle` 只证明本次读取到的字节闭包，不替应用签发账务 verified 或 claim observation。

离线验证回执应明确 `native_replayed=false`、`confirmation_reference_checked=false`。它可以复算固定 engine 语义下的账务和末状态估值，但没有重新调用 native engine，也没有访问确认集；更不能由此给任意来源、不支持的引擎、未来数据、全部尝试历史或研究科学有效性背书。

当前回归使用真实临时目录测试迁移、幂等内容身份、并发 no-replace、目标保留、全 role 篡改、缺失/额外/隐藏/symlink/FIFO、预算与注入；ENOSPC 和 parent fsync 使用故障注入区分提交前后边界。这些是软件回归证据，不是真实断电或所有平台认证。
