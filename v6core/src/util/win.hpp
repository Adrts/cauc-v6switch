// util/win.hpp — Win32 环境 RAII 助手：Winsock 初始化守卫、COM 初始化守卫、提权检测
#ifndef V6CORE_UTIL_WIN_HPP
#define V6CORE_UTIL_WIN_HPP

#include <string>
#include <winsock2.h>
#include <windows.h>

// Winsock 初始化守卫（inet_ntop / InetPtonW 前必须 WSAStartup）
class WsaGuard {
public:
    WsaGuard();
    ~WsaGuard();
    WsaGuard(const WsaGuard&) = delete;
    WsaGuard& operator=(const WsaGuard&) = delete;
    bool ok() const { return ok_; }

private:
    bool ok_ = false;
};

// COM 初始化守卫（设计文档 §5.1.3：DLL 自身初始化 COM，调用方线程无需处理）
// APARTMENTTHREADED 初始化；RPC_E_CHANGED_MODE 视为已初始化、退出时不 CoUninitialize。
class ComGuard {
public:
    ComGuard();
    ~ComGuard();
    ComGuard(const ComGuard&) = delete;
    ComGuard& operator=(const ComGuard&) = delete;
    bool ok() const { return ok_; }
    unsigned long hresult() const { return hr_; }

private:
    bool ok_ = false;
    bool need_uninit_ = false;
    unsigned long hr_ = 0;
};

// 当前进程是否持管理员令牌（TokenElevation）
bool is_elevated();

// 系统 netsh.exe 完整路径（GetSystemDirectory，避免 PATH 劫持）
std::wstring system_netsh_path();

#endif
