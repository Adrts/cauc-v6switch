// dns.cpp — v6_set_ipv6_dns：主路径 SetInterfaceDnsSettings（文档化 API，单次写入整表），
// 兜底 netsh 隐藏子进程；执行期快照回滚（§5.1.3/§5.1.4）。
// 参数层全量校验（InetPtonW）→ 定位 → 快照 → 写入 → 失败尽力回写原值。
#include "v6core.h"

#include <winsock2.h>
#include <ws2tcpip.h>
#include <mutex>
#include <string>
#include <vector>

#include "adapter.hpp"
#include "util/error.hpp"
#include "util/process.hpp"
#include "util/strutil.hpp"
#include "util/win.hpp"

namespace {

// ---- SetInterfaceDnsSettings（netioapi.h）----
// mingw-w64 头文件尚未收录该 API，结构与常量取自微软官方文档
// （learn.microsoft.com netioapi.h，Win10 Build 19041+）；
// 经 GetProcAddress 动态解析，避免静态导入拉高 DLL 加载基线（旧系统直接加载失败）。
struct DNS_INTERFACE_SETTINGS {
    ULONG Version;                 // DNS_INTERFACE_SETTINGS_VERSION1 = 1
    ULONG64 Flags;                 // DNS_SETTING_* 位图
    PWSTR Domain;                  // 未使用的选项字段必须清零（文档要求）
    PWSTR NameServer;              // 逗号/空格分隔的 DNS 服务器列表
    PWSTR SearchList;
    ULONG RegistrationEnabled;
    ULONG RegisterAdapterName;
    ULONG EnableLLMNR;
    ULONG QueryAdapterName;
    PWSTR ProfileNameServer;
};
constexpr ULONG kDnsSettingsVersion1 = 1;
constexpr unsigned long long kDnsSettingIpv6 = 0x0001;       // 仅作用于 IPv6 栈
constexpr unsigned long long kDnsSettingNameserver = 0x0002; // 配置静态 DNS 服务器

using SetInterfaceDnsSettingsFn =
    unsigned long (__stdcall *)(const GUID *, const DNS_INTERFACE_SETTINGS *);

SetInterfaceDnsSettingsFn set_dns_api() {
    static std::once_flag once;
    static SetInterfaceDnsSettingsFn fn = nullptr;
    std::call_once(once, [] {
        // iphlpapi 在本 DLL 导入表内（GetAdaptersAddresses），必然已加载
        if (HMODULE h = GetModuleHandleW(L"iphlpapi.dll"))
            fn = reinterpret_cast<SetInterfaceDnsSettingsFn>(
                GetProcAddress(h, "SetInterfaceDnsSettings"));
    });
    return fn;
}

// 一次调用写入整表静态 DNS（本文档场景恒为 IPv6 栈）
// 返回 true=成功；false=API 缺失或调用失败（err_code 带回调用错误码，缺失时置 0）
bool set_dns_static_api(const GUID& if_guid, const std::vector<std::wstring>& addrs,
                        unsigned long* err_code) {
    *err_code = 0;
    SetInterfaceDnsSettingsFn fn = set_dns_api();
    if (!fn) return false;
    std::wstring joined;
    for (size_t i = 0; i < addrs.size(); ++i) {
        if (i) joined += L',';
        joined += addrs[i];
    }
    DNS_INTERFACE_SETTINGS s{}; // 全零初始化：未设选项的字段清零
    s.Version = kDnsSettingsVersion1;
    s.Flags = kDnsSettingNameserver | kDnsSettingIpv6;
    s.NameServer = joined.data();
    const unsigned long rc = fn(&if_guid, &s);
    if (rc == NO_ERROR) return true;
    *err_code = rc;
    return false;
}

// netsh 兜底：逐条写入（首条 set 覆盖、其余 add 追加）。返回失败的序号，0=全部成功
int netsh_write_static_list(const std::wstring& name, const std::vector<std::wstring>& addrs) {
    const std::wstring netsh = system_netsh_path();
    for (size_t i = 0; i < addrs.size(); ++i) {
        std::wstring params = L"interface ipv6 ";
        if (i == 0) {
            params += L"set dnsservers name=" + cmd_quote(name) +
                      L" source=static address=" + addrs[0] + L" validate=no";
        } else {
            params += L"add dnsservers name=" + cmd_quote(name) +
                      L" address=" + addrs[i] + L" index=" + std::to_wstring(i + 1) +
                      L" validate=no";
        }
        ProcResult r = run_hidden(netsh, params);
        if (!r.launched) {
            v6err::set_win(V6_ERR_EXEC, r.last_err, "netsh 启动失败（第 %zu 步）", i + 1);
            return static_cast<int>(i) + 1;
        }
        if (r.exit_code != 0) {
            v6err::set(V6_ERR_EXEC, "netsh 设置第 %zu 条 DNS 失败（exit=%d）：%s",
                       i + 1, r.exit_code, r.output.c_str());
            return static_cast<int>(i) + 1;
        }
    }
    return 0;
}

// 快照回滚：恢复变更前的 DNS 状态（尽力而为）
// 已知局限（与设计 §5.1.3 一致的取舍）：GetAdaptersAddresses 无法区分"静态配置"
// 与"DHCPv6/RA 自动学习"的 DNS——对原本自动获取的接口回滚，会把自动学到的地址
// 固化为静态列表。彻底还原可执行 v6_reset（恢复 source=dhcp）。
void rollback(const GUID& if_guid, const std::wstring& name,
              const std::vector<std::wstring>& snapshot) {
    if (!snapshot.empty()) {
        unsigned long api_err = 0;
        if (set_dns_static_api(if_guid, snapshot, &api_err)) return;
        netsh_write_static_list(name, snapshot); // API 失败 → netsh 兜底，尽力而为
        return;
    }
    // 快照为空：恢复 DNS 自动获取（source=dhcp 语义在 netsh 侧文档化）
    const std::wstring params = L"interface ipv6 set dnsservers name=" +
                                cmd_quote(name) + L" source=dhcp";
    ProcResult r = run_hidden(system_netsh_path(), params);
    if (!(r.launched && r.exit_code == 0)) return; // 尽力而为
}

} // namespace

V6_API int v6_set_ipv6_dns(uint32_t if_index, const char** servers, int count) {
    // 1) 参数层全量校验（不触网、无需提权）
    if (!servers)
        return v6err::set(V6_ERR_PARAM, "servers 数组为 NULL");
    if (count < 1 || count > 16)
        return v6err::set(V6_ERR_PARAM, "DNS 数量 %d 超出范围（1 ≤ count ≤ 16）", count);

    std::vector<std::wstring> addrs;
    addrs.reserve(static_cast<size_t>(count));
    {
        WsaGuard wsa; // InetPtonW 需要 Winsock 就绪
        if (!wsa.ok())
            return v6err::set(V6_ERR_GENERIC, "WSAStartup 初始化 Winsock 失败");
        IN6_ADDR tmp{};
        for (int i = 0; i < count; ++i) {
            if (!servers[i])
                return v6err::set(V6_ERR_PARAM, "servers[%d] 为 NULL", i);
            const std::wstring wide = utf8_to_wide(servers[i]);
            if (!InetPtonW(AF_INET6, wide.c_str(), &tmp))
                return v6err::set(V6_ERR_PARAM, "servers[%d]（%s）不是合法 IPv6 地址", i, servers[i]);
            addrs.push_back(wide);
        }
    }

    // 2) 统一定位（IfIndex 不存在 → V6_ERR_PARAM，绝不盲目执行）
    AdapterInfo info;
    if (!lookup_adapter(if_index, &info)) return V6_ERR_PARAM;

    // 3) 防御位：应用进程必须已提权
    if (!is_elevated())
        return v6err::set(V6_ERR_ADMIN, "当前进程无管理员权限，无法设置 DNS");

    // 4) 执行期快照（当前 IPv6 DNS 列表，来自 GetAdaptersAddresses，不新增导出函数）
    const std::vector<std::wstring> snapshot = info.dns_v6;

    GUID if_guid{};
    if (!adapter_guid_from_string(info.guid, &if_guid))
        return v6err::set(V6_ERR_PARAM, "适配器 NetCfgInstanceId（%s）不是合法 GUID", info.guid.c_str());

    // 5) 写入：优先 API（单次整表写入）；API 缺失或失败 → netsh 逐条兜底
    unsigned long api_err = 0;
    const bool api_available = set_dns_api() != nullptr;
    const bool api_ok = api_available && set_dns_static_api(if_guid, addrs, &api_err);
    if (!api_ok) {
        const int failed_step = netsh_write_static_list(info.name, addrs);
        if (failed_step != 0) {
            const std::string detail = v6err::get(); // 保留 netsh 兜底失败细节
            rollback(if_guid, info.name, snapshot);  // 尽力回写原值
            const std::string api_note = !api_available
                ? "SetInterfaceDnsSettings 不可用（需 Windows 10 Build 19041+）"
                : "SetInterfaceDnsSettings 失败：" + v6err::win_text(api_err);
            if (snapshot.empty())
                return v6err::set(V6_ERR_EXEC,
                                  "%s；%s；已尝试恢复 DNS 自动获取，请刷新列表确认（建议执行 v6_reset）",
                                  api_note.c_str(), detail.c_str());
            return v6err::set(V6_ERR_EXEC,
                              "%s；%s；已尝试回写原 DNS 列表，请刷新列表确认（建议执行 v6_reset）",
                              api_note.c_str(), detail.c_str());
        }
    }
    return v6err::clear();
}
