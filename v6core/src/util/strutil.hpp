// util/strutil.hpp — 编码转换与转义（UTF-8 ↔ UTF-16、JSON 转义、命令行参数引号转义）
#ifndef V6CORE_UTIL_STRUTIL_HPP
#define V6CORE_UTIL_STRUTIL_HPP

#include <string>

// UTF-8 → UTF-16（失败/非法字节以替换处理，不抛异常）
std::wstring utf8_to_wide(const char* s, size_t len = static_cast<size_t>(-1));
inline std::wstring utf8_to_wide(const std::string& s) { return utf8_to_wide(s.data(), s.size()); }

// UTF-16 → UTF-8
std::string wide_to_utf8(const wchar_t* s, size_t len = static_cast<size_t>(-1));
inline std::string wide_to_utf8(const std::wstring& s) { return wide_to_utf8(s.data(), s.size()); }

// 指定代码页 → UTF-8（用于 netsh 控制台输出的 OEM 代码页文本）
std::string codepage_to_utf8(unsigned codepage, const char* s, size_t len);

// JSON 字符串转义：包裹引号并转义 " \ 与控制字符（其余字节原样透传，须为合法 UTF-8）
std::string json_escape(const std::string& utf8);

// Windows 命令行参数转义：按 MSVCRT/CommandLineToArgvW 规则加引号
// （空串强制 "；含空白或引号时加引号；内部引号转义、尾部反斜杠翻倍）
std::wstring cmd_quote(const std::wstring& s);

// 大小写不敏感包含匹配（ASCII 范围内，用于虚拟适配器名称启发）
bool contains_ci(const std::wstring& haystack, const wchar_t* needle);

#endif
