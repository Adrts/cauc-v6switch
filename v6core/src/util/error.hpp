// util/error.hpp — 线程局部错误描述存储 + 错误码设置助手
//
// 约定（设计文档 §5.1.1）：业务函数成功时清除线程错误，失败时写入描述；
// v6_last_error 为纯读取，不清除。跨边界仅传错误码，描述由同线程紧随读取。
#ifndef V6CORE_UTIL_ERROR_HPP
#define V6CORE_UTIL_ERROR_HPP

#include <string>
#include "v6core.h"

namespace v6err {

// 设置错误描述（printf 风格），返回 code。描述超长时截断。
int set(int code, const char* fmt, ...);

// 同上，但追加 ": " + Win32/HRESULT 错误文本（FormatMessageW 转 UTF-8）
int set_win(int code, unsigned long win_err, const char* fmt, ...);

// 清除当前线程错误描述，返回 V6_OK
int clear();

// 读取当前线程错误描述（无则为空串）
const char* get();

// Win32/HRESULT 错误码 → 简短 UTF-8 文本（失败时回退为十六进制数字）
std::string win_text(unsigned long code);

} // namespace v6err

#endif
