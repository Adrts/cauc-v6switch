// adapter.hpp — 内部共享：GetAdaptersAddresses 封装、按 IfIndex 定位、罗列 JSON 构建
#ifndef V6CORE_SRC_ADAPTER_HPP
#define V6CORE_SRC_ADAPTER_HPP

#include <memory>
#include <string>
#include <vector>
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>

// 单适配器信息（供操作函数定位与 DNS 快照使用）
struct AdapterInfo {
    uint32_t if_index = 0;
    std::wstring name;      // FriendlyName（连接名，如"以太网"）
    std::wstring desc;      // Description
    std::string guid;       // NetCfgInstanceId（"{" 包裹的 GUID 串，INetCfg 定位用）
    std::vector<std::wstring> dns_v6; // 当前 IPv6 DNS 列表（快照回滚用）
};

// RAII 持有 GetAdaptersAddresses 输出缓冲
struct FreeAdapterBuf {
    void operator()(IP_ADAPTER_ADDRESSES* p) const { if (p) free(p); }
};
using AdapterBufPtr = std::unique_ptr<IP_ADAPTER_ADDRESSES, FreeAdapterBuf>;

// GetAdaptersAddresses 输出（两段式取长重试）
// ok=false 表示枚举失败（线程错误已写）；ok=true 且 buf 为空表示系统中无适配器
struct AdapterList {
    AdapterBufPtr buf;
    bool ok = false;
};
AdapterList get_all_adapters();

// 按 IfIndex 定位适配器（操作函数统一定位前置流程，设计文档 §5.1.4）
// 找不到 → 返回 false 并写 V6_ERR_PARAM 错误；info 可为 nullptr（仅做存在性确认）
bool lookup_adapter(uint32_t if_index, AdapterInfo* info);

// "{"-包裹的 GUID 字符串（NetCfgInstanceId）→ GUID；非法返回 false（不写线程错误）
bool adapter_guid_from_string(const std::string& guid_str, GUID* out);

// 构建 v6_list_adapters 的 JSON 数组文本；ok=false 表示枚举失败（错误已写）
std::string build_adapters_json(bool* ok);

#endif
