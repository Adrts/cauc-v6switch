# cauc-v6switch 工程管理（设计文档 §5.6）
# 用法：
#   make        # dist/v6switch/（onedir，就地运行，含 v6core.dll）+ build/compile_commands.json
#   make clean  # 清理产物与中间文件
# Windows 下命令：make（scoop GNU Make）或 mingw32-make

# 编译器：llvm-mingw（clang + mingw-w64 UCRT），与项目根 .clangd 配置一致；命令行可用 CXX=... 覆盖
CXX       = D:/Toolchains/llvm-mingw-20260908-ucrt-x86_64/bin/clang++.exe
CXXFLAGS  = -std=c++17 -O2 -Wall -Wextra -D_WIN32_WINNT=0x0601
DLL_LIBS  = -lipHlpApi -lws2_32 -lole32 -loleaut32 -luuid -ladvapi32

VENV  := app/.venv
PY    := $(VENV)/Scripts/python.exe
SYSPY := python

DLL_SRC  := $(wildcard v6core/src/*.cpp) $(wildcard v6core/src/util/*.cpp)
DLL_HDR  := v6core/include/v6core.h $(wildcard v6core/src/*.hpp) $(wildcard v6core/src/util/*.hpp)

OBJ_DIR    := build/obj
DLL_OBJ    := $(addprefix $(OBJ_DIR)/,$(notdir $(DLL_SRC:.cpp=.o)))
COMPILE_DB := build/compile_commands.json

APP_DIR   := dist/v6switch
APP_EXE   := $(APP_DIR)/v6switch.exe
PYI_STAGE := build/pyinstaller-dist
APP_SRC   := $(wildcard app/v6switch/*.py) $(wildcard app/v6switch/bindings/*.py) \
             $(wildcard app/v6switch/resources/*) app/run.py app/pyproject.toml

.PHONY: all clean compile-db

all: compile-db $(APP_DIR)/v6core.dll $(APP_EXE)
	@echo DONE: $(APP_DIR)/v6core.dll $(APP_EXE) $(COMPILE_DB)

# ---- clangd 编译数据库：build/compile_commands.json（每次 make 重新生成） ----
compile-db: $(DLL_SRC) $(DLL_HDR) tools/gen_compile_commands.py
	@echo COMPILE_DB $(COMPILE_DB)
	@$(SYSPY) tools/gen_compile_commands.py --cxx "$(CXX)" --root "$(CURDIR)" \
		--out "$(COMPILE_DB)" --cxxflags "$(CXXFLAGS)" \
		--include v6core/include --include v6core/src --define V6CORE_BUILD \
		$(DLL_SRC)

# 目录创建：python 实现——scoop make（cmd shell）与 Git Bash make（sh shell）行为一致
MKDIR = python -c "import os,sys; [os.makedirs(p, exist_ok=True) for p in sys.argv[1:]]"

$(OBJ_DIR):
	@$(MKDIR) $@

# 模式规则按目标名匹配源：api.o → v6core/src/api.cpp；error.o → v6core/src/util/error.cpp
# 输出外显为 CXX/LD，完整命令行用 @ 静默（排查时 make V=1）
V = 0
Q = $(if $(filter 1,$(V)),,@)

$(OBJ_DIR)/%.o: v6core/src/%.cpp $(DLL_HDR) | $(OBJ_DIR)
	@echo CXX $<
	$(Q)$(CXX) $(CXXFLAGS) -Iv6core/include -Iv6core/src -DV6CORE_BUILD -c $< -o $@

$(OBJ_DIR)/%.o: v6core/src/util/%.cpp $(DLL_HDR) | $(OBJ_DIR)
	@echo CXX $<
	$(Q)$(CXX) $(CXXFLAGS) -Iv6core/include -Iv6core/src -DV6CORE_BUILD -c $< -o $@

# ---- ② 底层动态链接库：直接产出到交付目录 dist/v6switch/v6core.dll ----
# DLL 与 exe 同目录（bindings 按 exe 所在目录探测），不再在 dist/ 根留下副本
$(APP_DIR)/v6core.dll: $(DLL_OBJ) | $(APP_DIR)
	@echo LD $@
	$(Q)$(CXX) $(CXXFLAGS) -shared -static-libgcc -static-libstdc++ -o $@ $(DLL_OBJ) $(DLL_LIBS)
	@$(PY) -c "import pathlib; p=pathlib.Path('dist/v6core.dll'); p.unlink() if p.is_file() else None"

# ---- ① 应用层 venv（缺失时自动创建，不暴露为独立命令） ----
$(VENV)/Scripts/python.exe:
	@echo VENV $(VENV)
	python -m venv $(VENV)
	$(PY) -m pip install -e "app[dev]"

# ---- ① 应用层打包：dist/v6switch/（PyInstaller onedir，就地运行，不内嵌 DLL） ----
# onedir 不在启动时解压到 %TEMP%，启动更快；交付为目录，exe 从自身同目录加载 v6core.dll。
# 应用不使用 TLS，排除 ssl/_ssl 可避免打入 libssl（约 0.5MB）；
# 其余模块由 PyInstaller 按实际导入收集，Tcl/Tk 运行时由 tkinter 钩子自动收集
export PYI_LOG_LEVEL = WARN

$(APP_DIR):
	@$(MKDIR) $@

$(APP_EXE): $(VENV)/Scripts/python.exe $(APP_SRC) | $(APP_DIR)/v6core.dll $(APP_DIR)
	@echo PYINSTALLER $(APP_DIR)
	$(Q)$(PY) -m PyInstaller --noconfirm --noconsole --name v6switch $(PI_LOGFLAGS) \
		--exclude-module ssl --exclude-module _ssl \
		--add-data "$(abspath app/v6switch/resources);v6switch/resources" \
		--paths app --specpath build --workpath build/pyinstaller --distpath $(PYI_STAGE) \
		app/run.py
	@$(PY) tools/sync_onedir.py --src "$(PYI_STAGE)/v6switch" --dst "$(APP_DIR)" \
		--dll "$(APP_DIR)/v6core.dll" --config "dist/config.yaml"
	@$(PY) -c "import pathlib; p=pathlib.Path('dist/v6switch.exe'); p.unlink() if p.is_file() else None"

# ---- 清理（dist/v6switch/config.yaml 为用户自定义 DNS64 配置，会一并删除） ----
clean:
	python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('dist', 'build', 'app/v6switch.egg-info', '.pytest_cache')]"
