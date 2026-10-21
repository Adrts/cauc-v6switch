// ipv4.cpp — v6_set_ipv4 的实现路径：INetCfg 绑定开关（netcfgx COM，与 PowerShell
// Enable/Disable-NetAdapterBinding 同源）。COM 初始化由本模块 RAII 自理（§5.1.3）。
//
// 接口签名以工具链安装的 netcfgx.h 为准（mingw-w64 WIDL 生成，与官方 IDL 一致）：
//   INetCfg::Initialize(PVOID) / Apply() 无参 / EnumComponents(const GUID*, IEnum**)
//   INetCfgLock::AcquireWriteLock(DWORD, LPCWSTR, LPWSTR*) 三参、无 HWND
#include "v6core.h"

#include <winsock2.h> // 须先于 netcfgx.h 拉入的 windows.h
#include <initguid.h>
#include <netcfgx.h>
#include <devguid.h>

#include "adapter.hpp"
#include "netcfg.hpp"
#include "util/error.hpp"
#include "util/strutil.hpp"
#include "util/win.hpp"

namespace {

// COM 生存期与 INetCfg 释放的 RAII 聚合守卫
struct NetCfgSession {
    ComGuard com;
    INetCfg* nc = nullptr;
    INetCfgLock* lock = nullptr;
    bool initialized = false;
    bool locked = false;

    ~NetCfgSession() {
        // 先释放写锁，再反初始化并释放 INetCfg（写锁依附于该会话）
        if (lock) {
            if (locked) lock->ReleaseWriteLock();
            lock->Release();
        }
        if (nc) {
            if (initialized) nc->Uninitialize();
            nc->Release();
        }
    }
};

// HRESULT → 错误码（Access Denied 归提权位，其余归执行失败），并写线程错误描述
int map_hr(HRESULT hr, const char* what) {
    if (hr == E_ACCESSDENIED)
        return v6err::set_win(V6_ERR_ADMIN, static_cast<unsigned long>(hr), "%s 被拒绝访问", what);
    if (hr == 0) // 防御分支收到成功码：不引用 FormatMessage 的"操作成功"文案
        return v6err::set(V6_ERR_EXEC, "%s 失败（未返回具体错误码）", what);
    return v6err::set_win(V6_ERR_EXEC, static_cast<unsigned long>(hr), "%s 失败", what);
}

} // namespace

int netcfg_set_binding(uint32_t if_index, const wchar_t* component_id, bool enable) {
    // 1) 统一定位：if_index → 连接名 + NetCfgInstanceId（GUID 串）
    AdapterInfo info;
    if (!lookup_adapter(if_index, &info)) return V6_ERR_PARAM; // 错误已写

    // 2) 防御位：应用进程必须已提权（主链路启动即提权，正常不可达）
    if (!is_elevated())
        return v6err::set(V6_ERR_ADMIN, "当前进程无管理员权限，无法修改网络绑定");

    // 3) COM 会话（RAII：Uninitialize / ReleaseWriteLock / Release 全部自动收尾）
    NetCfgSession s;
    if (!s.com.ok())
        return v6err::set_win(V6_ERR_EXEC, s.com.hresult(), "CoInitializeEx 初始化 COM 失败");

    HRESULT hr = CoCreateInstance(CLSID_CNetCfg, nullptr, CLSCTX_INPROC_SERVER,
                                  IID_INetCfg, reinterpret_cast<void**>(&s.nc));
    if (FAILED(hr) || !s.nc)
        return map_hr(hr, "创建 CNetCfg COM 对象");

    // 4) 写锁（单写者保护：与 netsh/设备管理器等互斥）
    hr = s.nc->QueryInterface(IID_INetCfgLock, reinterpret_cast<void**>(&s.lock));
    if (FAILED(hr) || !s.lock)
        return map_hr(hr, "查询 INetCfgLock（单写者保护不可用）");
    {
        LPWSTR holder = nullptr;
        hr = s.lock->AcquireWriteLock(10 * 1000, L"cauc-v6switch", &holder);
        if (SUCCEEDED(hr)) {
            s.locked = true;
            if (holder) CoTaskMemFree(holder);
        } else {
            if (hr == E_ACCESSDENIED)
                return v6err::set_win(V6_ERR_ADMIN, static_cast<unsigned long>(hr),
                                      "获取网络配置写锁被拒绝访问");
            if (hr == NETCFG_E_NO_WRITE_LOCK)
                return v6err::set_win(V6_ERR_EXEC, static_cast<unsigned long>(hr),
                                      "获取网络配置写锁失败（正被其他程序占用，请稍后重试）");
            return map_hr(hr, "获取网络配置写锁");
        }
    }

    hr = s.nc->Initialize(nullptr);
    if (FAILED(hr)) return map_hr(hr, "初始化 INetCfg");
    s.initialized = true;

    // 5) 定位协议组件（ms_tcpip = IPv4）
    INetCfgComponent* proto = nullptr;
    hr = s.nc->FindComponent(component_id, &proto);
    if (FAILED(hr) || !proto)
        return v6err::set_win(V6_ERR_EXEC, hr, "未找到协议组件 ms_tcpip（IPv4）");

    // 6) 在网络适配器类中按 NetCfgInstanceId 匹配目标网卡组件
    //    匹配键 = GetInstanceGuid（即 NetCfgInstanceId，来自 GetAdaptersAddresses
    //    的 AdapterName 字段）。注意 GetId() 对网卡返回的是驱动 INF 标识
    //    （如 "yt6801.ndi"），不能作为 GUID 匹配键（仅作兜底比对）。
    GUID target{};
    if (!adapter_guid_from_string(info.guid, &target))
        return v6err::set(V6_ERR_PARAM, "适配器 NetCfgInstanceId（%s）不是合法 GUID", info.guid.c_str());

    IEnumNetCfgComponent* enum_nc = nullptr;
    hr = s.nc->EnumComponents(&GUID_DEVCLASS_NET, &enum_nc);
    if (FAILED(hr) || !enum_nc) {
        proto->Release();
        return v6err::set_win(V6_ERR_EXEC, hr, "枚举网络适配器组件失败");
    }

    INetCfgComponent* nic = nullptr;
    ULONG fetched = 0;
    while (enum_nc->Next(1, &nic, &fetched) == S_OK && fetched == 1) {
        GUID inst{};
        if (SUCCEEDED(nic->GetInstanceGuid(&inst)) && IsEqualGUID(inst, target))
            break; // nic 保持为当前组件
        LPWSTR id = nullptr; // 兜底：个别组件可能以 Id 字符串承载 GUID
        if (SUCCEEDED(nic->GetId(&id)) && id) {
            const bool matched = _wcsicmp(id, utf8_to_wide(info.guid).c_str()) == 0;
            CoTaskMemFree(id);
            if (matched) break;
        }
        nic->Release();
        nic = nullptr;
    }
    enum_nc->Release();
    if (!nic) {
        proto->Release();
        return v6err::set(V6_ERR_EXEC, "未在网络适配器组件中匹配到目标网卡（GUID %s）", info.guid.c_str());
    }

    // 7) 绑定开关
    INetCfgComponentBindings* bindings = nullptr;
    hr = proto->QueryInterface(IID_INetCfgComponentBindings, reinterpret_cast<void**>(&bindings));
    if (FAILED(hr) || !bindings) {
        nic->Release();
        proto->Release();
        return map_hr(hr, "查询 INetCfgComponentBindings");
    }

    hr = enable ? bindings->BindTo(nic) : bindings->UnbindFrom(nic);
    bindings->Release();
    nic->Release();
    proto->Release();
    if (FAILED(hr))
        return map_hr(hr, enable ? "开启 IPv4 绑定" : "关闭 IPv4 绑定");

    // 8) 提交（SUCCEEDED 覆盖 S_OK/NETCFG_S_REBOOT 等成功码）
    hr = s.nc->Apply();
    if (FAILED(hr)) return map_hr(hr, "应用网络配置（INetCfg::Apply）");
    return v6err::clear();
}

V6_API int v6_set_ipv4(uint32_t if_index, int enabled) {
    if (enabled != 0 && enabled != 1)
        return v6err::set(V6_ERR_PARAM, "enabled 参数非法（仅允许 0=关闭 / 1=开启）");
    return netcfg_set_binding(if_index, L"ms_tcpip", enabled == 1);
}
