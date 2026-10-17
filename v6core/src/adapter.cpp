#include "adapter.hpp"

#include <winsock2.h>
#include <ws2tcpip.h>
#include "util/error.hpp"
#include "util/json.hpp"
#include "util/strutil.hpp"
#include "util/win.hpp"

namespace {

// 罗列用标志：跳过 anycast/multicast（FriendlyName 必须保留）
constexpr ULONG kGaaFlags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST;

const sockaddr* addr_of(const SOCKET_ADDRESS& sa) { return sa.lpSockaddr; }

// sockaddr → 文本（失败返回空串）；调用方须已初始化 Winsock
std::string sockaddr_to_text(const sockaddr* sa) {
    if (!sa) return {};
    char buf[INET6_ADDRSTRLEN] = {0};
    const void* src = nullptr;
    if (sa->sa_family == AF_INET) {
        src = &reinterpret_cast<const sockaddr_in*>(sa)->sin_addr;
    } else if (sa->sa_family == AF_INET6) {
        src = &reinterpret_cast<const sockaddr_in6*>(sa)->sin6_addr;
    } else {
        return {};
    }
    return inet_ntop(sa->sa_family, const_cast<void*>(src), buf, sizeof(buf)) ? std::string(buf) : std::string();
}

// 虚拟适配器启发（设计文档 §5.1.2：IfType + 名称启发，前端默认过滤）
bool looks_virtual(const IP_ADAPTER_ADDRESSES* a) {
    if (a->IfType == IF_TYPE_SOFTWARE_LOOPBACK) return true;
    const std::wstring name = a->FriendlyName ? a->FriendlyName : L"";
    const std::wstring desc = a->Description ? a->Description : L"";
    static const wchar_t* kKeywords[] = {
        L"Hyper-V", L"vEthernet", L"WSL", L"Loopback", L"LoopBack Pseudo",
        L"TAP", L"VMware", L"VirtualBox", L"Virtual", L"WAN Miniport", L"PPP",
        L"Teredo", L"6to4", L"ISATAP", L"Bluetooth",
    };
    for (const wchar_t* kw : kKeywords) {
        if (contains_ci(name, kw) || contains_ci(desc, kw)) return true;
    }
    return false;
}

} // namespace

AdapterList get_all_adapters() {
    ULONG size = 16 * 1024;
    for (int attempt = 0; attempt < 6; ++attempt) {
        AdapterList result;
        result.buf.reset(static_cast<IP_ADAPTER_ADDRESSES*>(malloc(size)));
        if (!result.buf) {
            v6err::set(V6_ERR_GENERIC, "内存分配失败（%lu 字节）", static_cast<unsigned long>(size));
            return result; // ok=false
        }
        ULONG ret = GetAdaptersAddresses(AF_UNSPEC, kGaaFlags, nullptr, result.buf.get(), &size);
        if (ret == ERROR_SUCCESS) {
            result.ok = true;
            return result;
        }
        if (ret == ERROR_BUFFER_OVERFLOW) continue; // size 已被更新为所需大小，重试
        if (ret == ERROR_NO_DATA || ret == ERROR_ADDRESS_NOT_ASSOCIATED) {
            // 系统无适配器数据：视为成功、空列表
            result.buf.reset();
            result.ok = true;
            return result;
        }
        v6err::set_win(V6_ERR_GENERIC, ret, "GetAdaptersAddresses 枚举网络适配器失败");
        return result; // ok=false
    }
    v6err::set(V6_ERR_GENERIC, "GetAdaptersAddresses 缓冲区反复不足（异常环境）");
    return {};
}

bool lookup_adapter(uint32_t if_index, AdapterInfo* info) {
    AdapterList list = get_all_adapters();
    if (!list.ok) return false;              // 枚举失败：错误已写
    if (!list.buf) {                          // 系统无适配器：视为目标不存在
        v6err::set(V6_ERR_PARAM, "接口索引 %u 不存在（连接可能已断开或被移除，请刷新列表）", if_index);
        return false;
    }
    WsaGuard wsa; // inet_ntop 需要 Winsock 就绪
    for (const IP_ADAPTER_ADDRESSES* a = list.buf.get(); a; a = a->Next) {
        if (a->IfIndex != if_index || a->IfIndex == 0) continue;
        if (info) {
            info->if_index = if_index;
            info->name = a->FriendlyName ? a->FriendlyName : L"";
            info->desc = a->Description ? a->Description : L"";
            info->guid = a->AdapterName ? a->AdapterName : "";
            info->dns_v6.clear();
            for (const IP_ADAPTER_DNS_SERVER_ADDRESS* d = a->FirstDnsServerAddress; d; d = d->Next) {
                const sockaddr* sa = addr_of(d->Address);
                if (!sa || sa->sa_family != AF_INET6) continue;
                std::string text = sockaddr_to_text(sa);
                if (!text.empty()) info->dns_v6.push_back(utf8_to_wide(text));
            }
        }
        return true;
    }
    v6err::set(V6_ERR_PARAM, "接口索引 %u 不存在（连接可能已断开或被移除，请刷新列表）", if_index);
    return false;
}

bool adapter_guid_from_string(const std::string& guid_str, GUID* out) {
    if (!out) return false;
    const std::wstring wide = utf8_to_wide(guid_str);
    return wide.size() == 38 && SUCCEEDED(CLSIDFromString(wide.c_str(), out));
}

std::string build_adapters_json(bool* ok) {
    AdapterList list = get_all_adapters();
    if (!list.ok) {
        *ok = false;
        return {};
    }
    WsaGuard wsa;
    if (!wsa.ok()) {
        *ok = false;
        v6err::set(V6_ERR_GENERIC, "WSAStartup 初始化 Winsock 失败");
        return {};
    }

    JsonBuf jb;
    jb.begin_arr();
    for (const IP_ADAPTER_ADDRESSES* a = list.buf.get(); a; a = a->Next) {
        jb.begin_obj();
        jb.kv_str("name", wide_to_utf8(a->FriendlyName ? a->FriendlyName : L""));
        jb.kv_str("desc", wide_to_utf8(a->Description ? a->Description : L""));
        jb.kv_str("status", a->OperStatus == IfOperStatusUp ? "up" : "down");
        jb.kv_num("if_index", a->IfIndex);
        jb.key("ipv4").begin_arr();
        for (const IP_ADAPTER_UNICAST_ADDRESS* u = a->FirstUnicastAddress; u; u = u->Next) {
            std::string text = sockaddr_to_text(addr_of(u->Address));
            if (u->Address.lpSockaddr && u->Address.lpSockaddr->sa_family == AF_INET && !text.empty())
                jb.str(text);
        }
        jb.end_arr();
        jb.key("ipv6").begin_arr();
        for (const IP_ADAPTER_UNICAST_ADDRESS* u = a->FirstUnicastAddress; u; u = u->Next) {
            std::string text = sockaddr_to_text(addr_of(u->Address));
            if (u->Address.lpSockaddr && u->Address.lpSockaddr->sa_family == AF_INET6 && !text.empty())
                jb.str(text);
        }
        jb.end_arr();
        jb.key("dns_v4").begin_arr();
        for (const IP_ADAPTER_DNS_SERVER_ADDRESS* d = a->FirstDnsServerAddress; d; d = d->Next) {
            const sockaddr* sa = addr_of(d->Address);
            if (!sa || sa->sa_family != AF_INET) continue;
            std::string text = sockaddr_to_text(sa);
            if (!text.empty()) jb.str(text);
        }
        jb.end_arr();
        jb.key("dns_v6").begin_arr();
        for (const IP_ADAPTER_DNS_SERVER_ADDRESS* d = a->FirstDnsServerAddress; d; d = d->Next) {
            const sockaddr* sa = addr_of(d->Address);
            if (!sa || sa->sa_family != AF_INET6) continue;
            std::string text = sockaddr_to_text(sa);
            if (!text.empty()) jb.str(text);
        }
        jb.end_arr();
        jb.kv_bool("virtual", looks_virtual(a));
        jb.end_obj();
    }
    jb.end_arr();
    *ok = true;
    return jb.take();
}
