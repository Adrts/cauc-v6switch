// netcfg.hpp — 内部共享：INetCfg 绑定开关（与 Disable/Enable-NetAdapterBinding 同源）
#ifndef V6CORE_SRC_NETCFG_HPP
#define V6CORE_SRC_NETCFG_HPP

// 修改指定适配器（按 if_index 定位）上指定协议组件的绑定状态
// component_id 如 L"ms_tcpip"；enable=true 绑定，false 解绑
// 返回 V6_OK / V6_ERR_PARAM / V6_ERR_ADMIN / V6_ERR_EXEC（错误描述已写）
int netcfg_set_binding(uint32_t if_index, const wchar_t* component_id, bool enable);

#endif
