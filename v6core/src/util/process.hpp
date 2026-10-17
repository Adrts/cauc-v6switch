// util/process.hpp — 隐藏子进程执行（netsh 封装），捕获退出码与合并输出
#ifndef V6CORE_UTIL_PROCESS_HPP
#define V6CORE_UTIL_PROCESS_HPP

#include <string>

struct ProcResult {
    bool launched = false;   // CreateProcessW 是否成功
    unsigned long last_err = 0; // 未启动成功时的 GetLastError
    int exit_code = -1;      // 进程退出码（未启动时无意义）
    std::string output;      // stdout+stderr 合并输出（OEM 代码页转 UTF-8，截断至 1KB）
};

// 以 CREATE_NO_WINDOW + 隐藏窗口方式执行 exe（完整路径），阻塞至退出。
// params 为参数串（各参数应已经 cmd_quote 转义）。
ProcResult run_hidden(const std::wstring& exe_full_path, const std::wstring& params);

#endif
