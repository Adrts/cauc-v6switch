#include "util/process.hpp"

#include <string>
#include <vector>
#include <windows.h>
#include "util/strutil.hpp"

ProcResult run_hidden(const std::wstring& exe_full_path, const std::wstring& params) {
    ProcResult result;
    if (exe_full_path.empty()) { // 防御：空路径禁止交给系统搜索（防 PATH 劫持）
        result.last_err = ERROR_FILE_NOT_FOUND;
        return result;
    }

    // stdout/stderr 合并管道（读端不继承，写端可继承）
    SECURITY_ATTRIBUTES sa{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    HANDLE rd = nullptr, wr = nullptr;
    if (!CreatePipe(&rd, &wr, &sa, 0)) {
        result.last_err = GetLastError();
        return result;
    }
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW si{};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = wr;
    si.hStdError = wr;
    si.hStdInput = nullptr;
    PROCESS_INFORMATION pi{};

    // lpCommandLine 必须可写缓冲（CreateProcessW 原型要求），拼接 "exe" params
    std::wstring cmd = cmd_quote(exe_full_path);
    if (!params.empty()) {
        cmd += L' ';
        cmd += params;
    }
    std::vector<wchar_t> cmd_buf(cmd.begin(), cmd.end());
    cmd_buf.push_back(L'\0');

    BOOL ok = CreateProcessW(exe_full_path.c_str(), cmd_buf.data(), nullptr, nullptr, TRUE,
                             CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi);
    if (!ok) {
        result.last_err = GetLastError(); // 须先于任何 CloseHandle 读取，避免错误码被覆盖
        CloseHandle(wr);
        CloseHandle(rd);
        return result;
    }
    CloseHandle(wr); // 父进程立即关写端，读端读到 EOF 即子进程退出
    result.launched = true;

    // 排空管道至 EOF，再等进程退出；输出仅用于错误描述，读取量做上限保护
    constexpr size_t kMaxCapture = 64 * 1024;
    char buf[4096];
    DWORD n = 0;
    std::string raw;
    while (ReadFile(rd, buf, sizeof(buf), &n, nullptr) && n > 0) {
        if (raw.size() < kMaxCapture) {
            const size_t remain = kMaxCapture - raw.size();
            raw.append(buf, n < remain ? n : remain);
        }
    }
    CloseHandle(rd);

    bool timed_out = false;
    WaitForSingleObject(pi.hProcess, 60 * 1000);
    DWORD code = 0;
    if (GetExitCodeProcess(pi.hProcess, &code)) {
        if (code == STILL_ACTIVE) { // 60s 超时仍未退出：终止并按失败处理
            TerminateProcess(pi.hProcess, static_cast<UINT>(-1));
            WaitForSingleObject(pi.hProcess, 5 * 1000);
            timed_out = true;
            result.exit_code = -1;
        } else {
            result.exit_code = static_cast<int>(code);
        }
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    // netsh 输出为 OEM 代码页文本，转 UTF-8 并按字符边界截断（仅用于错误描述）
    std::string text = codepage_to_utf8(CP_OEMCP, raw.data(), raw.size());
    if (text.size() > 1024) {
        truncate_utf8(text, 1024);
        text += "...";
    }
    if (timed_out) text += "[子进程超时 60 秒，已终止]";
    result.output = std::move(text);
    return result;
}
