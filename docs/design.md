# CAUC IPv6 Switch 项目设计文档

| 项目 | 内容 |
| --- | --- |
| 项目名称 | cauc-v6switch（CAUC IPv6 Switch） |
| 版本 | v0.18（设计稿；列表契约移除 `binding_v4`，`v6_list_adapters` 退化为纯 `GetAdaptersAddresses`、彻底解除 INetCfg/COM 耦合；IPv4 状态改由 `ipv4[]` 近似表示） |
| 日期 | 2026-10-16 |
| 性质 | 练手 / 技术栈测试型小工具 |
| 核心测试目标 | **动态链接库（DLL）的封装与 FFI 调用**（主链路 Python ctypes；多语言样例暂缓） |
| 适用范围 | 仅针对 CAUC（中国民航大学）校内网络环境 |
| 平台 | Windows 10 / Windows 11 |

---

## 1. 项目概述

### 1.1 背景与目标

**业务目标**：CAUC 校园网 IPv6 连通性良好（教育网直连）。在需要体验 IPv6-only 网络时，要"禁用当前网络连接上的 IPv4 协议 + 为 IPv6 配置 DNS64 服务器"，手动操作繁琐且难还原，本工具将其一键化、可回滚；IPv4 资源经公共 NAT64/DNS64 服务（默认 nat64.net，备选 Trex / level66）访问。

**技术测试目标（项目主要目的）**：以该真实需求为载体，测试**动态链接库的封装与 FFI 调用**——实际底层操作全部封装进 C ABI 动态链接库，调用方通过稳定契约（头文件）衔接；主链路为 Python ctypes，多语言最小样例暂缓（§4.2）。

### 1.2 两部分组成

| 部分 | 形态 | 语言 | 职责 |
| --- | --- | --- | --- |
| ① 应用层 | Python 桌面程序（**GUI 单入口交付**；CLI 仅开发期） | Python 3.11（venv）+ PySide6 | GUI 可视化交互（唯一交付入口）；ctypes 调 DLL；**不含底层网络操作**。CLI 为开发/调试便利入口，**不随包分发** |
| ② 底层动态链接库 | `v6core.dll` | C++（导出 `extern "C"` C ABI） | **封装全部实际底层操作**：罗列连接、IPv4 开关、IPv6 DNS 设置、重置 |

**语言约束**：本机开发环境仅有 C/C++、Node.js、Python、Go。DLL 必须为 C/C++（C ABI 是四种语言共同互操作的唯一货币）；应用层选用 Python（GUI 与原中间层调度器同为 Python，合并为单进程）；多语言调用样例暂不实施（见 §4.2），DLL 的 C ABI 契约保持语言中立。

**调用链**：`GUI（交付）/ CLI（开发期）→ ctypes（C ABI）→ DLL`（单进程，无 IPC）。

### 1.3 合并为单进程应用的决策依据

1. **同语言无需跨进程**：GUI 与原中间层调度器同为 Python，IPC 进程隔离的解耦收益消失；合并后消除 IPC 编解码、子进程生命周期管理两大故障源；
2. **提权简化**：应用启动时自检管理员权限，无权限则以 `runas` 重启自身（一次 UAC），无需父子进程权限协调；
3. **开发期 CLI**：同一包保留 CLI 子命令入口（`list`/`set-ipv4`/`set-dns`/`reset`）供开发调试与自动化验证；**不随最终包分发**——GUI 本地运行、不依赖网络，重启 `v6switch.exe` 即可重置，无需 CLI 兜底；
4. **契约语言中立**：DLL 仍是唯一契约冻结点，不绑定任何调用语言；多语言样例暂缓（§4.2），未来补做不影响主产品。

### 1.4 非目标（明确不做）

- 不做开机自启、不常驻后台；
- 不针对 CAUC 以外的网络环境做适配或保证；
- 不实现 NAT64 网关探测等高级功能（可作为后续增强）；
- GUI 不追求炫丽，PySide6 原生控件即可，重心在链路与 FFI 正确性；
- 不做跨适配器的全局 IPv6-only：工具仅作用于用户选定的**单个网络连接**，其他活跃适配器（如 WLAN）的 IPv4 不受影响（风险说明见 §10）。

---

## 2. 术语与原理

| 术语 | 说明 |
| --- | --- |
| DNS64 | DNS 扩展，为只有 A 记录的域名合成 `64:ff9b::/96` 前缀的 AAAA 记录 |
| NAT64 | 网关设备，将合成 IPv6 地址的流量翻译为 IPv4 流量；本工具使用 nat64.net 提供的公共 NAT64 网关 |
| 适配器绑定（Binding） | 网络适配器上勾选的协议组件；IPv4 对应 ComponentID `ms_tcpip`，IPv6 对应 `ms_tcpip6` |
| C ABI | C 应用二进制接口（`extern "C"` 导出、基础类型与指针传参），跨语言互操作的事实标准 |
| FFI | 外部函数接口，如 Python ctypes、C/C++ LoadLibrary、Go syscall、Node.js koffi |
| 提权 | 修改网络绑定与 DNS 需要管理员权限；**应用进程**（GUI/CLI 均同）启动时自检，无权限以 `runas` 重启自身；DLL 不自行提权 |

**关键原理**：Windows 中 IPv4/IPv6 的 DNS 服务器配置**按协议栈分开管理**（`netsh interface ipv4` / `ipv6`）。禁用 IPv4 绑定后，DNS 查询走 IPv6 栈配置的 DNS 服务器，因此只需对 IPv6 栈设置 DNS64 地址即可。

---

## 3. 需求

### 3.1 功能需求

| 编号 | 需求 | 承载层 |
| --- | --- | --- |
| FR-1 | 罗列网络连接：适配器名称、描述、状态、接口索引、IPv4/IPv6 地址、当前 DNS（单次调用输出全部信息，兼作状态查询） | ② DLL |
| FR-2 | IPv4 开关：开启或关闭指定网络连接的 IPv4 绑定（`ms_tcpip`） | ② DLL |
| FR-3 | IPv6 DNS 设置：为指定网络连接设置 IPv6 DNS 服务器（DNS64 预设或自定义） | ② DLL |
| FR-4 | 重置：恢复指定网络连接的默认网络配置（IPv4 绑定开启 + IPv6/IPv4 DNS 恢复自动获取） | ② DLL |
| FR-5 | 管理员权限校验：应用启动时检测，无权限以 `runas` 重启自身（GUI/CLI 均同） | ① 应用 |
| FR-6 | DNS64 预设管理：内置预设（nat64.net / Trex / level66 节点表）+ 运行时自定义，配置文件持久化 | ① 应用 |
| FR-7 | 图形界面：适配器列表、状态面板、切换/重置按钮、预设下拉、操作日志区 | ① GUI |
| FR-8 | 终端 CLI 入口：子命令（`list`/`set-ipv4`/`set-dns`/`reset`），**开发期工具**，与 GUI 共用编排封装；仅用于开发调试与自动化验证，**不随包分发**（见 §5.6） | ① CLI（开发期） |

> 多语言最小调用样例（原 FR-9）**暂缓不做**（已决策，见 §4.2）；DLL 契约语言中立，未来可作为独立练手任务随时补做，不计入当前交付范围。

> "一键切换 IPv6-only"不是独立 DLL 函数，而是按固定顺序组合 **FR-3 → FR-2**（先设 IPv6 DNS64，后关 IPv4）的编排操作；编排封装于应用层 `core_ops.py`（GUI/CLI 共用），顺序铁律见 §11。

### 3.2 非功能需求

| 编号 | 需求 |
| --- | --- |
| NFR-1 | 轻量：无常驻服务、低内存占用；DLL 纯 Win32 实现，不引入运行时依赖 |
| NFR-2 | 快速：单次切换秒级完成，操作全程有反馈 |
| NFR-3 | 安全防呆：切换/重置需二次确认（GUI 弹窗、CLI 确认行）；自动跳过回环/虚拟适配器（可切换显示） |
| NFR-4 | 操作反馈：GUI 操作区实时回显每步结果（含错误描述）；**不写落盘日志文件** |
| NFR-5 | 契约稳定：`v6core.h`（FFI 契约）为单一真源，变更须同步全部调用方 |
| NFR-6 | 可维护：两个子项目独立构建，互不依赖源码，仅依赖头文件；切换/重置编排集中于一处（GUI/CLI 共用） |

---

## 4. 总体设计

### 4.1 架构图

```
┌────────────────────────────────────┐
│ ① 应用层（Python 3.11，venv）       │
│   GUI 入口：PySide6 图形界面        │
│   CLI 入口：终端子命令（开发期）     │
│   core_ops  切换/重置编排（共用）    │
│   bindings  [ctypes FFI]           │
└──────────────┬─────────────────────┘
               │ C ABI（extern "C"，UTF-8）
               ▼
┌────────────────────────────────────┐
│ ② v6core.dll（C++，C ABI 导出）     │
│  ├─ list    罗列网络连接            │
│  ├─ ipv4    IPv4 开关              │
│  ├─ dns     IPv6 DNS 设置          │
│  └─ reset   重置                   │
└────────────────────────────────────┘
               │
               ▼  done
```

### 4.2 FFI 调用链路与多语言扩展

**主产品链路（Python ctypes）**：

| 调用方 | 语言 | FFI 机制 | 定位 |
| --- | --- | --- | --- |
| 应用层（GUI/CLI 共用） | Python 3.11 | `ctypes.CDLL` + `argtypes/restype` | 主链路；指针/缓冲区构造、UTF-8 编解码、错误码转异常 |
| 扩展位（暂缓） | 任意 | 任意 | DLL 契约语言中立（C ABI），未来可随时追加最小样例（C / Go / Node.js），主产品不动 |

> **多语言最小样例（ffi-samples）暂不实施**（已决策）：主产品仅保留 Python ctypes 一条调用路径；`extern "C"` C ABI 契约本身不绑定任何调用语言，多语言验证降级为后续可选任务，需要时在 `tests/` 下追加最小样例即可。

**验证方式**：同一组 DLL 函数用例在应用侧统一执行比对（见 §8）。

### 4.3 工作流程

```
入口：① GUI 启动（python -m v6switch；交付唯一入口）
      （② 终端 CLI v6switch <cmd> 仅开发期使用，与 GUI 共用 bindings 与 core_ops；两入口启动时均自检提权，无权限 runas 重启）
 │
 ▼
[步骤1] 罗列网络连接（v6_list_adapters → JSON，含地址与 DNS）
 │
 ▼
[步骤2] 用户选择目标网络连接（默认选中已连接的物理适配器）
 │
 ▼
[步骤3] 显示当前状态（取自列表数据，无需独立查询）
 │
 ▼
[步骤4] 选择操作（二次确认后调用；core_ops 先做 if_index↔name 二次校验）
 │   ├─ 切换 IPv6-only（core_ops 编排，遵守顺序铁律）：
 │   │     a. v6_set_ipv6_dns(if_index, DNS64 服务器)   ← 先设 DNS，保持解析不断
 │   │     b. v6_set_ipv4(if_index, 0)                  ← 后关 IPv4
 │   │
 │   └─ 重置（还原默认网络配置）：
 │         v6_reset(if_index)                           ← IPv4 开启 + DNS 恢复自动获取
 ▼
结束
```

> 顺序铁律：**先 `v6_set_ipv6_dns` 成功、再 `v6_set_ipv4(0)`**，全程保持解析可用；由应用层 `core_ops` 统一遵守（§11）。

---

## 5. 详细设计

### 5.1 ② DLL 设计（核心）

#### 5.1.1 C ABI 契约（`v6core.h`，单一真源）

**对外仅提供 4 个业务函数 + 1 个错误配套函数**。设计原则：

- **C ABI 导出**（`extern "C" __declspec(dllexport)`，`__cdecl`）；
- **数据传递三模式**：①返回值只传错误码（`int`，不携带数据）；②入参一律只读借用（`const` 指针，调用期间有效，DLL 只读不持有）；③出参一律 caller-allocated 缓冲区（调用方分配、DLL 填充）——DLL 永不分配跨边界内存，故无需 free 函数；
- **字符串编码**：跨边界统一 UTF-8、`'\0'` 结尾；数组以 `count` 计数，不依赖边界探测；DLL 内部与 Win32 交互自行转 UTF-16；
- **错误处理**：业务函数返回码 `0` 成功、负数错误码；`v6_last_error()` 取线程局部错误描述（截断语义，返回写入长度，永不返回负数）；
- **结构化数据**：罗列结果统一序列化为 JSON 字符串输出，调用方自行解析（规避 C 结构体跨语言布局问题）；
- **空/非法缓冲区**：`buf == NULL || buf_len <= 0` 时——`v6_list_adapters` 返回 `V6_ERR_PARAM`；`v6_last_error` 返回 `0` 且不写任何字节（保持永不返回负数）；`buf_len >= 1` 时至少写入 `'\0'`，截断写入返回 `buf_len - 1`。

```c
/* 返回码约定 */
#define V6_OK            0
#define V6_ERR_GENERIC  -1
#define V6_ERR_PARAM    -2
#define V6_ERR_BUFFER   -3   /* 缓冲区不足（兜底路径，正常不触发） */
#define V6_ERR_ADMIN    -4   /* 应用进程未提权（防御位：主链路启动即提权，正常不可达） */
#define V6_ERR_EXEC     -5   /* 底层命令执行失败 */

/* 1. 罗列现有网络连接（一次调用完成）
 * 调用方传入预分配缓冲区（建议 64 KB，上界估算见 §5.1.2）：
 *   成功：返回 V6_OK，buf 写入 '\0' 结尾的 UTF-8 JSON 数组（字段见 §5.1.2）
 *   不足：返回 V6_ERR_BUFFER，调用方可扩容重试（仅兜底，正常不触发）
 * 兼作状态查询（GUI 状态面板数据源） */
int  v6_list_adapters(char* buf, int buf_len);

/* 2. 关闭或开启某个网络连接的 IPv4（enabled: 1=开启, 0=关闭）
 * if_index 为 v6_list_adapters 输出的 if_index 字段；0 为无效值 → V6_ERR_PARAM */
int  v6_set_ipv4(uint32_t if_index, int enabled);

/* 3. 设置某个网络连接的 IPv6 DNS
 * servers 为 UTF-8 IPv6 地址数组（DNS64 服务器），count 为数量（1 ≤ count ≤ 16） */
int  v6_set_ipv6_dns(uint32_t if_index, const char** servers, int count);

/* 4. 重置某个网络连接：IPv4 绑定恢复开启 + IPv6/IPv4 DNS 恢复自动获取 */
int  v6_reset(uint32_t if_index);

/* 配套：读取线程局部错误描述（须在同一线程、紧随失败调用后读取）
 * buf 由调用方分配；buf_len <= 0 或 buf == NULL 时返回 0 且不写；
 * buf_len 不足时截断写入但保证 '\0' 结尾，返回实际写入长度（不含 '\0'）；
 * 无待取描述时返回 0。永不返回负数。 */
int  v6_last_error(char* buf, int buf_len);
```

#### 5.1.2 罗列结果 JSON 字段与缓冲区上界

单适配器输出示例（`v6_list_adapters` JSON 数组的元素）：

```json
{
  "name": "以太网",
  "desc": "Intel(R) Ethernet Connection I219-V",
  "status": "up",
  "if_index": 12,
  "ipv4": ["10.132.0.8"],
  "ipv6": ["2001:da8:1005::1008", "fe80::a1b2:c3d4:ef01"],
  "dns_v4": ["202.115.0.10"],
  "dns_v6": [],
  "virtual": false
}
```

| 字段 | 内容 | 来源（Win32） |
| --- | --- | --- |
| `name` | 连接名（"以太网""WLAN"）——**GUI/CLI 展示与确认用；`core_ops` 执行前以 `if_index`↔`name` 配对做二次校验（§5.1.4）** | `GetAdaptersAddresses` → `FriendlyName` |
| `desc` | 硬件/驱动描述 | 同上 → `Description` |
| `status` | up / down | `OperStatus` |
| `if_index` | 接口索引，netsh 定位用 | `IfIndex` |
| `ipv4[]` / `ipv6[]` | 当前各栈单播地址（IPv4 关闭后 `ipv4` 为空数组） | `FirstUnicastAddress` 按 `sa_family` 分组 |
| `dns_v4[]` / `dns_v6[]` | 两栈各自当前 DNS 服务器 | `FirstDnsServerAddress` 按协议族分组 |
| `virtual` | 回环/Hyper-V/WSL/TAP 等虚拟适配器标记，前端默认过滤（NFR-3） | `IfType` + 名称启发 |

> **IPv4 状态由 `ipv4[]` 近似表示（列表不引入绑定查询字段）**：本工具流程中，关闭 IPv4 绑定的动作只发生在 `v6_set_ipv4`，因此"`ipv4[]` 为空"可直接作为"IPv4 已关闭"的显示与复核代理；它不区分"绑定关闭"与"绑定开启但未获取到地址"（如 DHCP 未拿到地址），但对本工具用途足够。**列表全程仅用 `GetAdaptersAddresses`，不触碰 `INetCfg`/COM**——这正是列表轻量、稳定、无单点故障放大的关键。

**一次调用的缓冲区上界估算**（因此无需探测式取长，主路径一次调用完成）：

| 项 | 估算 |
| --- | --- |
| 单适配器 JSON（名称/描述 ≤ 256 B + 地址/DNS 数组通常每栈 ≤ 5 项） | 典型 < 1 KB |
| 适配器数量（普通 5–15；装满虚拟化/VPN 全家桶 30–50） | 上界几十个 |
| 全列表输出 | 典型 < 20 KB，极端 < 50 KB |

调用方直接给 **64 KB 固定缓冲区，一次调用完成**；`V6_ERR_BUFFER` 仅作封装层兜底（bindings 自动扩容重试一次），GUI/CLI 不会走到该路径。对比：`GetAdaptersAddresses` 自身必须两段式探测（原生结构体展开动辄数百 KB、无廉价上界），本契约输出为紧凑文本、上界明确，固定容量即可。

#### 5.1.3 DLL 内部实现策略

| 功能 | 主路径 | 备注 |
| --- | --- | --- |
| 罗列网络连接 | Win32 `GetAdaptersAddresses`（iphlpapi） | 文档化 API；**纯 `GetAdaptersAddresses`，无 COM 依赖**；地址与 DNS 信息并入同一 JSON 输出 |
| IPv4 绑定开关 | `INetCfg`（netcfgx，COM） | 与 `Disable-NetAdapterBinding` 同源；MinGW 若缺 `netcfgx.h` 等头文件，内嵌接口声明（COM 本质为 C ABI 虚表，IID/CLSID 公开）；复杂度超预期再**降级**：DLL 内隐藏进程调 `netsh interface set binding` |
| IPv6 DNS 设置 | `netsh interface ipv6 set dnsservers` 隐藏子进程 | 无公开的按协议族 DNS 设置 API，务实取舍；首条 `set ... source=static address=<a1> validate=no`（覆盖原列表）+ 其余逐条 `add ... validate=no` 追加；**变更前用 `GetAdaptersAddresses` 记录当前 IPv6 DNS 列表做快照，执行中途失败则尽力回写原值（回滚）**再返回错误码；连接名由 DLL 内转换并转义 |
| 重置 | 组合内部逻辑：IPv4 绑定开启 + `netsh ... set dnsservers source=dhcp`（v4/v6 各一次） | 即恢复默认网络配置＝**恢复自动获取(DHCP/RA)，非快照还原**（原为静态 DNS 时不会被还原） |

> **COM 初始化归属**：DLL 使用 `INetCfg` 前由**自身**在每个导出函数入口以 RAII 守卫调用 `CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED)`；返回 `RPC_E_CHANGED_MODE`（调用方已 MTA）视为已初始化、不再 `CoUninitialize`，其余情况退出时 `CoUninitialize`。调用方（Python 线程）无需关心 COM 初始化——符合 §11 分层铁律。

#### 5.1.4 操作函数参数与校验（`if_index` 方案）

**键选择决策**：三个操作函数以 `uint32_t if_index`（系统接口索引）定位目标接口，而非连接名或自造序号——

- 自造列表序号：随枚举顺序漂移，两次刷新间可指向不同网卡，否决；
- 连接名：唯一且跨重启稳定，但中文/空格（"以太网"）引入跨语言编码与命令行转义负担，**退役为展示与校验字段**；
- IfIndex：系统级唯一、适配器存在期间稳定；跨语言参数面零编码歧义（ctypes `c_uint32` / C 原生 / Go `uint32` / koffi `'uint32'`），netsh 注入面从调用方侧消失。

**统一定位前置流程**（三个操作函数共用，调用方只传一个数字）：

```
uint32_t if_index（0 为无效值 → V6_ERR_PARAM）
  → GetAdaptersAddresses 按 IfIndex 匹配
     ├─ 匹配不到（拔出/卸载/索引失效）→ V6_ERR_PARAM，绝不盲目执行
     └─ 匹配成功 → 一次取得：连接名（DLL 内转 UTF-16 + netsh 命令行转义）、
        NetCfgInstanceId/GUID（INetCfg 用）、存在性确认
```

> IfIndex 稳定性边界：适配器存在期间（含禁用/启用、含本工具的绑定开关）索引不变且不会被新增接口夺走；适配器**消失后**索引失效、可能被系统回收复用给新接口。复用导致的误指由 **`core_ops` 执行前 `if_index`↔`name` 配对二次校验**拆除（新接口的连接名不可能与已占用名称相同）；连接名/编码/转义负担由此全部内聚于 DLL 内部，调用方无需触碰。

**参数约束**：

| 函数 | 参数 | 约束 | 非法时 |
| --- | --- | --- | --- |
| `v6_set_ipv4` | `if_index` | 非 0 且列表中存在 | `V6_ERR_PARAM` |
| | `enabled` | 仅 1（开启）/ 0（关闭） | `V6_ERR_PARAM` |
| `v6_set_ipv6_dns` | `if_index` | 同上 | `V6_ERR_PARAM` |
| | `servers` | 非 NULL；每项非 NULL 且为合法 IPv6 地址（`InetPtonW(AF_INET6)` 校验） | `V6_ERR_PARAM` |
| | `count` | `1 ≤ count ≤ 16`（防御上限，工具场景 2–3 个足够） | `V6_ERR_PARAM` |
| `v6_reset` | `if_index` | 同上 | `V6_ERR_PARAM` |

**执行语义与失败映射**：

| 函数 | 执行语义 | 失败映射 |
| --- | --- | --- |
| `v6_set_ipv4` | 单次成败（底层路径见 §5.1.3） | Access Denied → `V6_ERR_ADMIN`；Apply/netsh 失败 → `V6_ERR_EXEC` |
| `v6_set_ipv6_dns` | **参数层全量校验 + 执行期快照回滚**：先校验全部地址；变更前存快照，中途失败尽力回写原值 | 参数非法 → `V6_ERR_PARAM`；任一条 exit code 非 0 → `V6_ERR_EXEC`（`v6_last_error` 附"列表可能不完整，建议 `v6_reset`"） |
| `v6_reset` | **尽力还原**：某步失败仍继续后续步骤，返回首个失败的错误码 | 同上 |

> **DNS 回滚说明**：`v6_set_ipv6_dns` 的"全成"仅覆盖参数层；执行期出现"首条 `set` 已生效、后续 `add` 失败"时，DLL 用变更前快照**尽力回滚**，回滚仍失败则返回 `V6_ERR_EXEC`，由 `core_ops` 提示用户执行 `v6_reset`。快照复用 `GetAdaptersAddresses` 读取，不新增导出函数。

DLL 执行后不自动回读，调用方刷新列表（看 `ipv4[]`/`dns_v6`）确认效果——DLL 保持无状态，不引入查询函数。

### 5.2 ① 应用层设计（GUI 单入口交付；CLI 开发期保留）

**同一 Python 包 `v6switch` 的两个入口**，共用 bindings 与 core_ops 编排：

1. **GUI 入口（唯一交付入口）**（`python -m v6switch` 或 `v6switch-gui`）：PySide6 图形界面（见 §5.3），随 `v6switch.exe` 分发；
2. **CLI 入口（开发期保留，不随包分发）**：交互菜单 `[1] 罗列网络连接 [2] 切换 IPv6-only（先设 DNS64 后关 IPv4）[3] 重置 [0] 退出`；或子命令 `v6switch list|set-ipv4|set-dns|reset|presets`（与 4 个导出函数对应）。仅用于开发调试与自动化验证；最终交付包**不含**此入口（`--noconsole` 生成窗口子系统 exe、无控制台句柄，见 §5.6）。

- **FFI 绑定**（`bindings/v6core.py`）：`ctypes.CDLL("v6core.dll")`，逐函数声明 `argtypes`/`restype`；提供类型安全函数（缓冲区自动构造/扩容重试、UTF-8 编解码、错误码转异常）；**错误码转异常必须在同一线程、紧随 DLL 调用返回完成**——`v6_last_error` 为线程局部，禁止跨线程缓存或延迟读取；若经 QThread 调用 DLL，由该工作线程就地读取并抛异常，再经 signal 回传异常对象给主线程；
- **编排封装**（`core_ops.py`）：`switch_to_ipv6(if_index, name, dns)` 与 `reset(if_index, name)` 两个高层函数，固化两条铁律：**执行前 `if_index`↔`name` 配对二次校验**（重新罗列并比对，不符提示刷新重选，防目标消失后索引被复用导致误操作，见 §5.1.4）与**先 DNS 后关 IPv4 的切换顺序**；GUI 与 CLI 一律调它，禁止各自拼 DLL 调用序列；
- **提权**：启动时 `ctypes.windll.shell32.IsUserAnAdmin()` 检测；无权限以 `ShellExecuteW(..., "runas", sys.executable, ...)` 重启自身（触发一次 UAC），拒绝降权运行；
- **依赖**：交付依赖仅 PySide6；`rich`（CLI 美化）为**开发期可选依赖**，不进入打包；venv 管理。

### 5.3 GUI 界面设计（PySide6 / Qt Widgets）

- **界面布局**（单窗口）：
  - 顶部：适配器 `QTableWidget`（名称/描述/状态/IP 摘要）+ 刷新按钮；
  - 中部：所选适配器状态面板（IPv4 地址状态——`ipv4[]` 是否为空、当前 DNS）；
  - 底部：DNS64 预设下拉（读共享 `config.toml`）+ 自定义地址 + [切换 IPv6-only] [重置] + 日志 `QPlainTextEdit`（只读）；
  - 切换/重置前 `QMessageBox.question` 二次确认；
- **构建/打包**：开发期直接 `python -m v6switch` 运行；分发由根 `Makefile` 的 `exe` 目标调 PyInstaller 打单文件 exe（`--onefile --noconsole`），详见 §5.6；
- **选型说明**：PySide6（Qt 官方 Python 绑定，LGPL）控件成熟、观感现代；重心仍是链路与 FFI 正确性，不做复杂界面动效。

### 5.4 DNS64 预设（`config.toml`）

路径 `%APPDATA%\v6switch\config.toml`，首次运行由应用自动生成：

| Provider | 位置 | DNS64 地址 |
| --- | --- | --- |
| nat64.net | Amsterdam | `2a00:1098:2b::1` |
| nat64.net | Ashburn | `2a01:4ff:f0:9876::1` |
| nat64.net | Helsinki | `2a01:4f9:c010:3f02::1` |
| nat64.net | London | `2a00:1098:2c::1` |
| nat64.net | Nuremberg | `2a01:4f8:c2c:123f::1` |
| Trex | Tampere | `2001:67c:2b0::4` |
| Trex | Tampere | `2001:67c:2b0::6` |
| level66 | Germany | `2001:67c:2960::64` |
| level66 | Germany | `2001:67c:2960::6464` |

> **默认预设「nat64.net 多节点」**：Amsterdam + London + Nuremberg 三个地址按序写入（`count = 3`，在 `v6_set_ipv6_dns` 的 1–16 上限内）。GUI 预设下拉可选任意单节点（`count = 1`）或默认组合，亦可运行时输入自定义 DNS64 地址（FR-6，config.toml 持久化）。

### 5.5 错误处理

| 场景 | 处理 |
| --- | --- |
| 应用未提权 | 启动时检测，`runas` 重启自身（一次 UAC）；用户拒绝提权则退出并说明 |
| 目标接口不存在/列表已变化 | `core_ops` 执行前 `if_index`↔`name` 配对二次校验，不符提示刷新重选；DLL 侧匹配不到 → `V6_ERR_PARAM` |
| 连接名含空格/中文/特殊字符 | 跨边界只传 `if_index`（纯数字，无编码歧义）；DLL 内部转 UTF-16 并对 netsh 命令行转义 |
| DLL 函数失败 | 负错误码 + `v6_last_error`；若 DNS 已设成功而关闭 IPv4 失败，`core_ops` 提示并建议执行 `v6_reset` 恢复 |
| 调用方缓冲区不足 | `V6_ERR_BUFFER` 仅作兜底（主路径 64 KB 固定缓冲区一次调用，正常不触发，见 §5.1.2）；`bindings` 封装层自动扩容重试一次 |
| 安全软件拦截 netsh/INetCfg | 明确错误码与提示，建议放行 |

### 5.6 构建与交付（Make）

根目录 `Makefile` 统一管理编译与打包（Windows 下命令为 `mingw32-make`，可别名 `make`）：

| 目标 | 动作 | 产物 |
| --- | --- | --- |
| `make dll` | g++ 编译链接 `v6core/`（`-static-libgcc -static-libstdc++`，链接 iphlpapi/ole32 等） | `dist/v6core.dll` |
| `make exe` | venv 内 PyInstaller 打包应用（`--onefile --noconsole`，**不内嵌 DLL**） | `dist/v6switch.exe` |
| `make all` | `dll + exe`（默认目标） | 两个最终产物 |
| `make test-dll` | g++ 编译并运行 `v6core/tests/` C++ 单元测试（纯 `<cassert>`，无第三方框架） | — |
| `make test` | `test-dll` + pytest（`tests/python/`） | — |
| `make clean` | 清理中间产物 | — |

- **最终产物仅两个文件，分离分发**：`v6core.dll`（C ABI 库）+ `v6switch.exe`（单文件 exe，内嵌 Python 运行时与 PySide6，**不含 DLL**，**仅含 GUI 入口**）。两文件须放在同一目录；exe 运行时从**自身同目录**加载 `v6core.dll`，`bindings` 探测顺序：① exe/主模块同目录 → ② 开发期项目 `dist/` → ③ 加载失败弹窗提示缺 DLL；`make exe` 不使用 `--add-binary`；
- **打包入口收敛为 GUI 单入口**：`--onefile --noconsole` 生成窗口子系统 exe，无控制台句柄，无法承载 CLI。故交付包只含 GUI；CLI 入口仅存在于源码/开发环境（`python -m v6switch.cli`）。**不做**"按参数分支让同一 exe 兼作 GUI/CLI"的方案（否则要么破坏 `--noconsole`、要么 GUI 启动闪控制台窗口）；
- 工具链前置：MinGW-w64（g++/mingw32-make）、Python 3.11 venv（`pyproject.toml` 含 pyinstaller）。
- **venv 路径与测试联动**：Makefile 显式 `VENV := app/.venv`；`make test` 用 `$(VENV)/Scripts/python -m pytest tests/python`，并先依赖 `make dll`，确保 ctypes 能加载真实 DLL。

---

## 6. 技术选型

| 部分 | 选型 | 理由 | 备选 |
| --- | --- | --- | --- |
| ② DLL | C++（MinGW-w64 / GCC）+ Make，导出 C ABI | 本机 C 工具链为 MinGW（自带 g++/mingw32-make）；`extern "C" __declspec(dllexport)` 在 GCC 下同样生效，x64 调用约定统一，C ABI 是全部四种环境语言互操作的唯一货币；静态链接 GCC 运行时（`-static-libgcc -static-libstdc++`）保持单 DLL 零依赖（NFR-1） | MSVC + CMake |
| ① 应用层 | Python 3.11（venv）：PySide6 GUI（交付）+ CLI（开发期），ctypes | 同语言合并单进程；ctypes FFI 成熟；PySide6（Qt Widgets）控件成熟、观感现代；交付仅 GUI，CLI 不进包 | GUI 可回退 Tkinter；FFI 可换 Go（`syscall`）/ Node.js（`koffi`） |
| 工程管理 | **Make**（根 `Makefile`）：`dll` 目标编译 v6core.dll，`exe` 目标 PyInstaller 打包，`all = dll + exe` | 一条命令串起编译→测试→打包；**最终产物收敛为 `v6core.dll` + `v6switch.exe` 两个文件**（详见 §5.6） | CMake + 手工脚本 |
| FFI 样例 | 暂缓（见 §4.2） | 主产品保留 Python ctypes 单链路；DLL 契约语言中立，样例可作为后续练手任务随时补做 | C / Go / Node.js |

> 语言约束：本机仅有 C/C++、Node.js、Python、Go。**唯一契约（`v6core.h`）不动**——未来应用层换 GUI 框架（如 Tkinter）或换语言（Go Wails），只替换应用层实现。

---

## 7. 项目结构

```
cauc-v6switch/
├── Makefile                     # 工程管理：make dll / make exe / make all / make test / make test-dll / make clean
├── docs/                        # 文档（本文件）
│   └── design.md
├── v6core/                      # ② 底层动态链接库
│   ├── include/v6core.h         # C ABI 契约（单一真源）
│   ├── src/
│   │   ├── api.cpp              # 导出函数实现（参数校验/JSON 封装）
│   │   ├── adapter.cpp          # v6_list_adapters（GetAdaptersAddresses）
│   │   ├── ipv4.cpp             # v6_set_ipv4（INetCfg 绑定开关）
│   │   ├── dns.cpp              # v6_set_ipv6_dns（netsh 子进程封装）
│   │   ├── reset.cpp            # v6_reset（恢复默认配置）
│   │   └── util/                # 编码转换/进程/错误/JSON（与 Win32 解耦，便于单测）
│   └── tests/                   # DLL 侧 C++ 单元测试（JSON/编码/命令构造/截断；make test-dll）
│       └── test_units.cpp
├── app/                         # ① 应用层（GUI 交付入口 + CLI 开发期入口，同一包同一 venv）
│   ├── v6switch/
│   │   ├── __main__.py          # GUI 入口：python -m v6switch（唯一交付入口）
│   │   ├── cli.py               # CLI 入口：v6switch <cmd>（开发期工具，不随包分发）
│   │   ├── gui.py               # PySide6 界面
│   │   ├── core_ops.py          # 切换/重置编排（身份校验 + 顺序铁律，GUI/CLI 共用）
│   │   ├── presets.py           # config.toml 读写
│   │   ├── admin.py             # 提权检测 + runas 重启自身
│   │   └── bindings/v6core.py   # ctypes 绑定封装
│   └── pyproject.toml
├── tests/
│   └── python/                  # bindings mock DLL、core_ops 编排用例
└── dist/                        # 最终产物：v6core.dll + v6switch.exe（make 生成）
```

---

## 8. 测试与验收

**DLL 用例验证**（核心）：每个导出函数 × 常规/边界用例，在应用侧统一执行比对：

| 用例 | DLL 基准 | Python 应用 |
| --- | --- | --- |
| `v6_list_adapters` 缓冲区不足（兜底路径）→ 扩容重试 | 基准 | 重试一致 |
| `v6_list_adapters` 中文适配器名 | UTF-8 输出 | 解析一致 |
| `v6_set_ipv4` 传入无效/已失效 `if_index`（含 0） | `V6_ERR_PARAM` | 同 |
| `v6_set_ipv6_dns` 合法/非法 IPv6 地址 | 基准 / `V6_ERR_PARAM` | 一致 |
| 切换序列（`v6_set_ipv6_dns` → `v6_set_ipv4(0)`）全流程 | 基准 | 一致 |
| `v6_reset` 往返（切换后重置恢复默认） | 基准 | 一致 |

**单元测试**：DLL 侧（`v6core/tests/`，`make test-dll`：JSON 序列化/转义、UTF-8↔UTF-16、netsh 命令行构造与转义、`v6_last_error` 截断）；Python 侧（bindings 封装 mock DLL、core_ops 编排）。

**手动验收清单**（CAUC 校内网络真机）：

1. GUI 与 CLI 分别以普通权限/管理员运行，提权自检与 `runas` 重启行为正确；
2. GUI 与 CLI 罗列适配器结果一致（含中文名称）；
3. GUI 切换后 `ipconfig /all`：无 IPv4 地址、IPv6 DNS 为 DNS64 地址；
4. 切换后可解析 IPv4-only 域名并经 NAT64 访问；
5. 选择目标后、执行前人为变更网络连接（插入 USB 网卡/启用虚拟交换机/拔出目标），验证 `if_index`↔`name` 二次校验拒绝执行或安全失败，**无误操作其他接口**；
6. **仅用终端 CLI（开发期入口）完成"重置"**：验证 CLI 与 GUI 共用 core_ops、行为一致（该路径仅开发期可用，交付包不提供）；
7. 重置后 `ipconfig /all` 确认 IPv4 恢复、IPv6/IPv4 DNS 恢复自动获取。

---

## 9. 里程碑

> 顺序原则：**先 DLL + CLI 磨稳 FFI 契约与编排，再套 GUI，最后 Make 打包交付**——契约冻结点逐个落地，避免返工。

| 阶段 | 内容 | 交付 |
| --- | --- | --- |
| M1 | 工程骨架（根 Makefile：`dll`/`test` 目标）+ v6core.dll：`v6_list_adapters`（FR-1）+ 错误机制 + ctypes 绑定验证 C ABI | `make dll` 产物在 Python 侧跑通 |
| M2 | DLL 修改函数：`v6_set_ipv4` / `v6_set_ipv6_dns` / `v6_reset`（FR-2/3/4）；CLI 入口（开发期）+ core_ops 编排 + 提权（FR-5/6/8） | 终端入口全功能可用（开发期验证路径就绪） |
| M3 | PySide6 GUI（FR-7），与 CLI 共用 core_ops | GUI 全功能可用 |
| M4 | `exe` 打包目标（PyInstaller，GUI 单入口）+ README + 发布 | `make all` → `v6core.dll` + `v6switch.exe`，完整 v0.1 |

数据分析/统计类功能（如切换历史分析）暂缓，优先完成核心基础功能。

---

## 10. 风险与限制

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 跨边界字符编码错误（中文适配器名"以太网"） | 乱码/崩溃 | 全链路统一 UTF-8；矩阵专门用例 |
| 缓冲区大小/内存边界错误 | 调用方崩溃 | caller-allocated 原则；固定容量（64 KB）一次调用 + `V6_ERR_BUFFER` 兜底重试 |
| GUI 与 CLI 编排实现漂移 | 行为不一致 | 切换/重置编排强制集中于 `core_ops.py`，双入口共用 |
| 调用方编排顺序错误（先关 IPv4 后设 DNS） | 切换期间解析中断 | 顺序铁律固化在 `core_ops.py`（§11）；禁止绕过它直接调 DLL 序列 |
| MinGW 头文件不完整 / INetCfg（COM）复杂度超预期 | M1/M2 延期 | 内嵌 COM 接口声明；兜底降级：DLL 内 netsh 子进程 |
| nat64.net 不可达（网络策略封锁/服务下线） | 切换后无法访问 IPv4 资源 | DNS 先设、IPv4 后禁；`v6_reset` 兜底；可换用其他内置预设节点（Trex / level66）或自定义 |
| 切换失败/断网后需还原 | 用户锁死 v6-only | 工具本地运行、不依赖网络，重启 `v6switch.exe` 用 GUI `v6_reset` 恢复默认；必要时用系统"网络和 Internet 设置"手工恢复 |
| 安全软件拦截修改 | 操作失败 | 明确报错并提示放行 |
| 操作非目标适配器（期间接口增删、索引复用） | 其他网络受损 | 单接口作用域 + 二次确认；`core_ops` 执行前 `if_index`↔`name` 配对二次校验，不符拒绝执行 |
| 仅适配 Windows | 跨平台不可用 | 明确平台约束（CAUC 场景以 Windows 为主） |
| PyInstaller × PySide6 单文件 exe 体积偏大/启动慢 | 交付体验 | 接受体积（单文件便携优先）；必要时 `--exclude-module` 裁剪未用 Qt 模块 |

---

## 11. 约定

- 文档目录为本仓库 `docs/`；方案变更须同步更新本文档；
- Python 依赖一律走 venv，禁止全局 pip；
- 契约真源：`v6core.h`（FFI）——任何变更必须先改契约，再同步应用层实现与本文档；
- 分层铁律：应用层不做底层网络操作、DLL 不做用户交互；
- **COM 初始化归属**：DLL 自身以 RAII 初始化/释放 COM（`CoInitializeEx`），调用方线程无需处理（见 §5.1.3）；
- **错误读取铁律**：错误码转异常须在同一线程、紧随 DLL 调用返回完成，禁止跨线程缓存或延迟读取 `v6_last_error`（见 §5.2）；
- **身份校验铁律：执行任何变更前，`core_ops` 必须重新罗列并以 `if_index`↔`name` 配对校验目标接口**——不符（目标消失/索引被复用）一律拒绝执行并提示刷新重选；
- **切换顺序铁律：必须先 `v6_set_ipv6_dns` 成功、再 `v6_set_ipv4(0)`**；还原一律用 `v6_reset`——固化于 `core_ops.py`，GUI/CLI 一律经它调用，禁止各自拼 DLL 调用序列。
- GUI设计考虑极限拉伸缩放环境，各个元素必须完整展示，如有必要可以设置最小窗口尺寸。

---

## 12. 开放问题

已全部关闭：

1. GUI 框架 → **PySide6**（已决策，§5.3 / §6）；
2. ffi-samples 三语言样例 → **暂缓不做**（已决策，§4.2；DLL 契约语言中立，未来可作为独立练手任务随时补做）。
