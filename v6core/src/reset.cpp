// reset.cpp — v6_reset：恢复默认网络配置（尽力还原）
// IPv4 绑定恢复开启 + IPv6/IPv4 DNS 恢复自动获取（DHCP/RA，非快照还原）
// 某步失败仍继续后续步骤，返回首个失败的错误码（§5.1.4 执行语义）
#include "v6core.h"

#include <string>

#include "adapter.hpp"
#include "netcfg.hpp"
#include "util/error.hpp"
#include "util/process.hpp"
#include "util/strutil.hpp"
#include "util/win.hpp"

namespace {

// netsh 恢复某协议栈 DNS 自动获取（source=dhcp 语义在 netsh 侧文档化；
// SetInterfaceDnsSettings 对"清空静态→回 DHCP"的 NULL 语义未文档化，故此处保留 netsh）
std::string dns_to_dhcp(const std::wstring& name, const wchar_t* stack) {
    const std::wstring params = std::wstring(L"interface ") + stack +
                                L" set dnsservers name=" + cmd_quote(name) + L" source=dhcp";
    ProcResult r = run_hidden(system_netsh_path(), params);
    if (!r.launched)
        return "netsh 启动失败：" + v6err::win_text(r.last_err);
    if (r.exit_code != 0)
        return "netsh exit=" + std::to_string(r.exit_code) + "：" + r.output;
    return {};
}

} // namespace

V6_API int v6_reset(uint32_t if_index) {
    // 1) 统一定位
    AdapterInfo info;
    if (!lookup_adapter(if_index, &info)) return V6_ERR_PARAM;

    // 2) 防御位：应用进程必须已提权
    if (!is_elevated())
        return v6err::set(V6_ERR_ADMIN, "当前进程无管理员权限，无法重置网络配置");

    // 3) 尽力还原：某步失败仍继续后续步骤，返回首个失败的错误码
    int first_err = V6_OK;
    std::string first_detail;

    // 3a. IPv4 绑定恢复开启（INetCfg）
    {
        int rc = netcfg_set_binding(if_index, L"ms_tcpip", true);
        if (rc != V6_OK && first_err == V6_OK) {
            first_err = rc;
            first_detail = v6err::get();
        }
    }

    // 3b. IPv4 DNS → 自动获取
    {
        std::string detail = dns_to_dhcp(info.name, L"ipv4");
        if (!detail.empty() && first_err == V6_OK) {
            first_err = V6_ERR_EXEC;
            first_detail = "恢复 IPv4 DNS 自动获取失败：" + detail;
        }
    }

    // 3c. IPv6 DNS → 自动获取
    {
        std::string detail = dns_to_dhcp(info.name, L"ipv6");
        if (!detail.empty() && first_err == V6_OK) {
            first_err = V6_ERR_EXEC;
            first_detail = "恢复 IPv6 DNS 自动获取失败：" + detail;
        }
    }

    if (first_err != V6_OK)
        return v6err::set(first_err, "%s（其余步骤已尽力执行）", first_detail.c_str());
    return v6err::clear();
}
