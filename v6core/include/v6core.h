/*
 * v6core.h — CAUC IPv6 Switch 底层动态链接库 C ABI 契约（单一真源）
 *
 * 设计文档：docs/design.md §5.1.1
 * 变更本文件前先改设计文档，再同步全部调用方（NFR-5）。
 *
 * 数据传递约定：
 *   - 返回值只传错误码（int），不携带数据；
 *   - 入参一律只读借用（const 指针），DLL 只读不持有；
 *   - 出参一律 caller-allocated 缓冲区，DLL 永不分配跨边界内存，无需 free 函数；
 *   - 字符串编码统一 UTF-8、'\0' 结尾；数组以 count 计数；
 *   - DLL 内部与 Win32 交互自行转 UTF-16。
 */
#ifndef V6CORE_H
#define V6CORE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef V6CORE_BUILD
#define V6_API __declspec(dllexport) __cdecl
#else
#define V6_API __declspec(dllimport) __cdecl
#endif

/* 返回码约定 */
#define V6_OK            0
#define V6_ERR_GENERIC  -1
#define V6_ERR_PARAM    -2
#define V6_ERR_BUFFER   -3   /* 缓冲区不足（兜底路径，正常不触发） */
#define V6_ERR_ADMIN    -4   /* 应用进程未提权（防御位：主链路启动即提权，正常不可达） */
#define V6_ERR_EXEC     -5   /* 底层命令执行失败 */

/* 1. 罗列现有网络连接（一次调用完成）
 * 调用方传入预分配缓冲区（建议 64 KB，上界估算见设计文档 §5.1.2）：
 *   成功：返回 V6_OK，buf 写入 '\0' 结尾的 UTF-8 JSON 数组
 *   不足：返回 V6_ERR_BUFFER（buf 内容未定义、调用方不得读取），可扩容重试
 *   buf == NULL 或 buf_len <= 0：返回 V6_ERR_PARAM
 * 兼作状态查询（GUI 状态面板数据源）。 */
V6_API int  v6_list_adapters(char* buf, int buf_len);

/* 2. 关闭或开启某个网络连接的 IPv4（enabled: 1=开启, 0=关闭）
 * if_index 为 v6_list_adapters 输出的 if_index 字段；0 为无效值 → V6_ERR_PARAM */
V6_API int  v6_set_ipv4(uint32_t if_index, int enabled);

/* 3. 设置某个网络连接的 IPv6 DNS
 * servers 为 UTF-8 IPv6 地址数组（DNS64 服务器），count 为数量（1 ≤ count ≤ 16） */
V6_API int  v6_set_ipv6_dns(uint32_t if_index, const char** servers, int count);

/* 4. 重置某个网络连接：IPv4 绑定恢复开启 + IPv6/IPv4 DNS 恢复自动获取 */
V6_API int  v6_reset(uint32_t if_index);

/* 配套：读取线程局部错误描述（须在同一线程、紧随失败调用后读取）
 * buf 由调用方分配；buf_len <= 0 或 buf == NULL 时返回 0 且不写；
 * buf_len 不足时截断写入但保证 '\0' 结尾，返回实际写入长度（不含 '\0'）；
 * 无待取描述时返回 0。永不返回负数。 */
V6_API int  v6_last_error(char* buf, int buf_len);

#ifdef __cplusplus
}
#endif

#endif /* V6CORE_H */
