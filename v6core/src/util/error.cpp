#include "util/error.hpp"

#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <windows.h>
#include "util/strutil.hpp"

namespace {

// 线程局部错误描述（MinGW-w64 / GCC 17+ 支持 thread_local 动态初始化）
thread_local std::string t_err_msg;

constexpr size_t kMaxErrLen = 2048;

std::string vformat(const char* fmt, va_list ap) {
    char stack_buf[1024];
    va_list ap_copy;
    va_copy(ap_copy, ap); // vsnprintf 消费 va_list；大消息需二次格式化，必须复制
    int n = vsnprintf(stack_buf, sizeof(stack_buf), fmt, ap);
    if (n < 0) {
        va_end(ap_copy);
        return fmt ? fmt : "";
    }
    if (static_cast<size_t>(n) < sizeof(stack_buf)) {
        va_end(ap_copy);
        return std::string(stack_buf, static_cast<size_t>(n));
    }
    std::string out(static_cast<size_t>(n) + 1, '\0');
    vsnprintf(out.data(), out.size(), fmt, ap_copy);
    va_end(ap_copy);
    out.resize(static_cast<size_t>(n));
    return out;
}

} // namespace

namespace v6err {

int set(int code, const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::string msg = vformat(fmt, ap);
    va_end(ap);
    if (msg.size() > kMaxErrLen) msg.resize(kMaxErrLen);
    t_err_msg = std::move(msg);
    return code;
}

int set_win(int code, unsigned long win_err, const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::string msg = vformat(fmt, ap);
    va_end(ap);
    msg += ": ";
    msg += win_text(win_err);
    if (msg.size() > kMaxErrLen) msg.resize(kMaxErrLen);
    t_err_msg = std::move(msg);
    return code;
}

int clear() {
    t_err_msg.clear();
    return V6_OK;
}

const char* get() {
    return t_err_msg.c_str();
}

std::string win_text(unsigned long code) {
    // 常见 HRESULT/错误码的中文系统返回中文文本，转 UTF-8 供上层展示
    LPWSTR buf = nullptr;
    DWORD n = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                                 FORMAT_MESSAGE_IGNORE_INSERTS,
                             nullptr, code,
                             MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
                             reinterpret_cast<LPWSTR>(&buf), 0, nullptr);
    std::string out;
    if (n > 0 && buf) {
        out = wide_to_utf8(buf, n);
        LocalFree(buf);
    } else {
        char tmp[32];
        snprintf(tmp, sizeof(tmp), "0x%08lX", code);
        out = tmp;
    }
    // 去掉尾部换行与空白（FormatMessage 常带 \r\n）
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r' || out.back() == ' ')) out.pop_back();
    return out;
}

} // namespace v6err
