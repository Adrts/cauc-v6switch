#include "util/json.hpp"

#include <cstdio>
#include "util/strutil.hpp"

void JsonBuf::comma() {
    if (need_comma_) out_ += ',';
    need_comma_ = true;
}

JsonBuf& JsonBuf::begin_obj() { comma(); out_ += '{'; need_comma_ = false; return *this; }
JsonBuf& JsonBuf::end_obj()   { out_ += '}'; need_comma_ = true;  return *this; }
JsonBuf& JsonBuf::begin_arr() { comma(); out_ += '['; need_comma_ = false; return *this; }
JsonBuf& JsonBuf::end_arr()   { out_ += ']'; need_comma_ = true;  return *this; }

JsonBuf& JsonBuf::key(const char* k) {
    comma();
    out_ += json_escape(k);
    out_ += ':';
    need_comma_ = false; // 键之后跟值，值前不需要逗号
    return *this;
}

JsonBuf& JsonBuf::str(const std::string& utf8) { comma(); out_ += json_escape(utf8); return *this; }

JsonBuf& JsonBuf::boolean(bool b) { comma(); out_ += b ? "true" : "false"; return *this; }

JsonBuf& JsonBuf::number(uint32_t v) {
    comma();
    char tmp[16];
    snprintf(tmp, sizeof(tmp), "%u", v);
    out_ += tmp;
    return *this;
}

JsonBuf& JsonBuf::kv_str(const char* k, const std::string& utf8) { key(k).str(utf8); return *this; }
JsonBuf& JsonBuf::kv_bool(const char* k, bool b) { key(k).boolean(b); return *this; }
JsonBuf& JsonBuf::kv_num(const char* k, uint32_t v) { key(k).number(v); return *this; }

std::string JsonBuf::take() { return std::move(out_); }
