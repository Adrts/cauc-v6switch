// util/json.hpp — 极简 JSON 输出器（仅用于 v6_list_adapters 序列化，不解析）
#ifndef V6CORE_UTIL_JSON_HPP
#define V6CORE_UTIL_JSON_HPP

#include <cstdint>
#include <string>

class JsonBuf {
public:
    JsonBuf& begin_obj();
    JsonBuf& end_obj();
    JsonBuf& begin_arr();
    JsonBuf& end_arr();
    JsonBuf& key(const char* k);          // 写 "k":（自动补逗号）
    JsonBuf& str(const std::string& utf8); // 写转义后的字符串值
    JsonBuf& boolean(bool b);
    JsonBuf& number(uint32_t v);
    // 便捷组合：键 + 字符串值 / 键 + 布尔 / 键 + 数字
    JsonBuf& kv_str(const char* k, const std::string& utf8);
    JsonBuf& kv_bool(const char* k, bool b);
    JsonBuf& kv_num(const char* k, uint32_t v);
    std::string take();

private:
    void comma();
    std::string out_;
    bool need_comma_ = false;
};

#endif
