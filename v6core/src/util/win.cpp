#include "util/win.hpp"

#include <winsock2.h>
#include <objbase.h>

WsaGuard::WsaGuard() {
    WSADATA data{};
    ok_ = WSAStartup(MAKEWORD(2, 2), &data) == 0;
}

WsaGuard::~WsaGuard() {
    if (ok_) WSACleanup();
}

ComGuard::ComGuard() {
    hr_ = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (hr_ == static_cast<unsigned long>(RPC_E_CHANGED_MODE)) {
        ok_ = true;            // 调用线程已按 MTA 初始化：视为已初始化，不再补 CoUninitialize
        need_uninit_ = false;
    } else if (SUCCEEDED(hr_)) {
        ok_ = true;
        need_uninit_ = true;
    }
}

ComGuard::~ComGuard() {
    if (ok_ && need_uninit_) CoUninitialize();
}

bool is_elevated() {
    BOOL elevated = FALSE;
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return false;
    DWORD ret_len = 0;
    TOKEN_ELEVATION elev{};
    BOOL ok = GetTokenInformation(token, TokenElevation, &elev, sizeof(elev), &ret_len);
    CloseHandle(token);
    if (!ok) return false;
    elevated = elev.TokenIsElevated;
    return elevated != FALSE;
}

std::wstring system_netsh_path() {
    wchar_t sys_dir[MAX_PATH];
    UINT n = GetSystemDirectoryW(sys_dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return {}; // 失败返回空串（调用方按启动失败处理，禁止回退 PATH 搜索）
    return std::wstring(sys_dir, n) + L"\\netsh.exe";
}
