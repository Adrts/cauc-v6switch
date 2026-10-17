#include "util/strutil.hpp"

#include <windows.h>
#include <cstring>

std::wstring utf8_to_wide(const char* s, size_t len) {
    if (!s) return {};
    if (len == static_cast<size_t>(-1)) len = strlen(s);
    if (len == 0) return {};
    int need = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, static_cast<int>(len), nullptr, 0);
    if (need <= 0) {
        // 含非法字节：降级为不校验模式，避免整条消息丢失
        need = MultiByteToWideChar(CP_UTF8, 0, s, static_cast<int>(len), nullptr, 0);
        if (need <= 0) return {};
    }
    std::wstring out(static_cast<size_t>(need), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s, static_cast<int>(len), out.data(), need);
    return out;
}

std::string wide_to_utf8(const wchar_t* s, size_t len) {
    if (!s) return {};
    if (len == static_cast<size_t>(-1)) len = wcslen(s);
    if (len == 0) return {};
    int need = WideCharToMultiByte(CP_UTF8, 0, s, static_cast<int>(len), nullptr, 0, nullptr, nullptr);
    if (need <= 0) return {};
    std::string out(static_cast<size_t>(need), '\0');
    WideCharToMultiByte(CP_UTF8, 0, s, static_cast<int>(len), out.data(), need, nullptr, nullptr);
    return out;
}

std::string codepage_to_utf8(unsigned codepage, const char* s, size_t len) {
    if (!s || len == 0) return {};
    if (len > 0x7FFFFFFF) len = 0x7FFFFFFF;
    int need = MultiByteToWideChar(static_cast<UINT>(codepage), 0, s, static_cast<int>(len), nullptr, 0);
    if (need <= 0) return std::string(s, len); // 转换失败：原样透传
    std::wstring wide(static_cast<size_t>(need), L'\0');
    MultiByteToWideChar(static_cast<UINT>(codepage), 0, s, static_cast<int>(len), wide.data(), need);
    return wide_to_utf8(wide);
}

std::string json_escape(const std::string& utf8) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(utf8.size() + 2);
    out += '"';
    for (unsigned char c : utf8) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b";  break;
            case '\f': out += "\\f";  break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (c < 0x20) {
                    // 控制字符 → \u00XX（UTF-8 中控制字符恒为单字节）
                    out += "\\u00";
                    out += kHex[(c >> 4) & 0xF];
                    out += kHex[c & 0xF];
                } else {
                    out += static_cast<char>(c); // 其余字节（UTF-8 多字节序列）原样透传
                }
        }
    }
    out += '"';
    return out;
}

std::wstring cmd_quote(const std::wstring& s) {
    bool need = s.empty();
    for (wchar_t c : s) {
        if (c == L' ' || c == L'\t' || c == L'"') { need = true; break; }
    }
    if (!need) return s;
    std::wstring out;
    out += L'"';
    size_t bs = 0; // 连续反斜杠计数
    for (wchar_t c : s) {
        if (c == L'\\') {
            ++bs;
        } else {
            if (c == L'"') out.append(bs * 2 + 1, L'\\'); // 引号前反斜杠翻倍 + 转义引号
            else out.append(bs, L'\\');
            bs = 0;
            out += c;
        }
    }
    out.append(bs * 2, L'\\'); // 尾部反斜杠翻倍，避免转义收尾引号
    out += L'"';
    return out;
}

bool contains_ci(const std::wstring& haystack, const wchar_t* needle) {
    if (!needle) return false;
    const size_t nlen = wcslen(needle);
    if (nlen == 0 || haystack.size() < nlen) return false;
    const size_t hlen = haystack.size();
    for (size_t i = 0; i + nlen <= hlen; ++i) {
        size_t j = 0;
        while (j < nlen) {
            wchar_t a = haystack[i + j], b = needle[j];
            if (a >= L'A' && a <= L'Z') a = static_cast<wchar_t>(a - L'A' + L'a');
            if (b >= L'A' && b <= L'Z') b = static_cast<wchar_t>(b - L'A' + L'a');
            if (a != b) break;
            ++j;
        }
        if (j == nlen) return true;
    }
    return false;
}
