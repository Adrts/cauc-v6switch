// api.cpp — 导出函数入口：v6_list_adapters / v6_last_error（含缓冲区语义）
// 分层铁律：本文件只做参数校验、编排与 JSON 装载，不触碰具体网络操作实现。
#ifndef V6CORE_BUILD
#define V6CORE_BUILD
#endif
#include "v6core.h"

#include <cstring>
#include "adapter.hpp"
#include "util/error.hpp"

V6_API int v6_list_adapters(char* buf, int buf_len) {
    if (!buf || buf_len <= 0) {
        return v6err::set(V6_ERR_PARAM, "无效输出缓冲区（buf=NULL 或 buf_len<=0）");
    }
    bool ok = false;
    std::string json = build_adapters_json(&ok);
    if (!ok) return V6_ERR_GENERIC; // 错误描述已写
    const size_t need = json.size() + 1;
    if (need > static_cast<size_t>(buf_len)) {
        return v6err::set(V6_ERR_BUFFER,
                          "罗列结果需要 %zu 字节（含结尾 NUL），超过缓冲区 %d 字节",
                          need, buf_len);
    }
    memcpy(buf, json.c_str(), need);
    return v6err::clear();
}

V6_API int v6_last_error(char* buf, int buf_len) {
    if (!buf || buf_len <= 0) return 0; // 不写任何字节，永不返回负数
    const char* msg = v6err::get();
    const size_t total = strlen(msg); // 不含 NUL
    size_t n = total;
    if (n >= static_cast<size_t>(buf_len)) n = static_cast<size_t>(buf_len) - 1; // 截断，保证 NUL
    // 回退到 UTF-8 字符边界：避免把多字节中文切成非法序列（调用方按 UTF-8 解码）
    while (n > 0 && (static_cast<unsigned char>(msg[n]) & 0xC0) == 0x80) --n;
    if (n > 0) memcpy(buf, msg, n);
    buf[n] = '\0';
    return static_cast<int>(n);
}
