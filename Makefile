# cauc-v6switch 工程管理（设计文档 §5.6）
# 目标：dll（v6core.dll）/ exe（v6switch.exe）/ all / test / clean / venv
# Windows 下命令：make（scoop GNU Make）或 mingw32-make

# 编译器：llvm-mingw（clang + mingw-w64 UCRT），与项目根 .clangd 配置一致；命令行可用 CXX=... 覆盖
CXX       = D:/Toolchains/llvm-mingw-20260908-ucrt-x86_64/bin/clang++.exe
CXXFLAGS  = -std=c++17 -O2 -Wall -Wextra -D_WIN32_WINNT=0x0601
DLL_LIBS  = -lipHlpApi -lws2_32 -lole32 -loleaut32 -luuid -ladvapi32

VENV     := app/.venv
PY       := $(VENV)/Scripts/python.exe

DLL_SRC  := $(wildcard v6core/src/*.cpp) $(wildcard v6core/src/util/*.cpp)
DLL_HDR  := v6core/include/v6core.h $(wildcard v6core/src/*.hpp) $(wildcard v6core/src/util/*.hpp)

.PHONY: all dll exe test venv clean

all: dll exe

# ---- ② 底层动态链接库：dist/v6core.dll（逐源文件编译 .o → 统一链接） ----
# 对象文件平铺到 build/obj/（顶层与 util/ 子目录各源文件基名互不冲突）
OBJ_DIR  := build/obj
DLL_OBJ  := $(addprefix $(OBJ_DIR)/,$(notdir $(DLL_SRC:.cpp=.o)))

dll: dist/v6core.dll

# 目录创建：python 实现——scoop make（cmd shell）与 Git Bash make（sh shell）行为一致；
# sh 下 mkdir 无 -p 且反斜杠路径不可用，cmd 下 mkdir -p 不可用，故不用 shell 原生 mkdir
MKDIR = python -c "import os,sys; [os.makedirs(p, exist_ok=True) for p in sys.argv[1:]]"

$(OBJ_DIR):
	@$(MKDIR) $@

# 模式规则按目标名匹配源：api.o → v6core/src/api.cpp；error.o → v6core/src/util/error.cpp
# 输出外显为 CXX/LD，完整命令行用 @ 静默（排查时去掉 @ 或 make V=1）
V = 0
Q = $(if $(filter 1,$(V)),,@)

$(OBJ_DIR)/%.o: v6core/src/%.cpp $(DLL_HDR) | $(OBJ_DIR)
	@echo CXX $<
	$(Q)$(CXX) $(CXXFLAGS) -Iv6core/include -Iv6core/src -DV6CORE_BUILD -c $< -o $@

$(OBJ_DIR)/%.o: v6core/src/util/%.cpp $(DLL_HDR) | $(OBJ_DIR)
	@echo CXX $<
	$(Q)$(CXX) $(CXXFLAGS) -Iv6core/include -Iv6core/src -DV6CORE_BUILD -c $< -o $@

dist/v6core.dll: $(DLL_OBJ) | dist
	@echo LD $@
	$(Q)$(CXX) $(CXXFLAGS) -shared -static-libgcc -static-libstdc++ -o $@ $(DLL_OBJ) $(DLL_LIBS)

dist:
	@$(MKDIR) $@

# ---- ① 应用层 venv 与依赖（仅 venv，禁止全局 pip） ----
$(VENV)/Scripts/python.exe:
	python -m venv $(VENV)
	$(PY) -m pip install -e "app[dev]"

venv: $(VENV)/Scripts/python.exe

# ---- ① 应用层打包：dist/v6switch.exe（--onefile --noconsole，不内嵌 DLL） ----
# 体积裁剪（§10）：仅用 QtWidgets/QtCore/QtGui，排除未用的 Qt 模块与重依赖
PI_EXCLUDES := \
	--exclude-module PySide6.QtWebEngineCore \
	--exclude-module PySide6.QtWebEngineWidgets \
	--exclude-module PySide6.QtWebEngineQuick \
	--exclude-module PySide6.QtWebChannel \
	--exclude-module PySide6.QtWebSockets \
	--exclude-module PySide6.QtQml \
	--exclude-module PySide6.QtQuick \
	--exclude-module PySide6.QtQuickWidgets \
	--exclude-module PySide6.QtQuickControls2 \
	--exclude-module PySide6.QtQuick3D \
	--exclude-module PySide6.QtMultimedia \
	--exclude-module PySide6.QtMultimediaWidgets \
	--exclude-module PySide6.QtNetwork \
	--exclude-module PySide6.QtNetworkAuth \
	--exclude-module PySide6.QtPdf \
	--exclude-module PySide6.QtPdfWidgets \
	--exclude-module PySide6.QtSvg \
	--exclude-module PySide6.QtSvgWidgets \
	--exclude-module PySide6.QtCharts \
	--exclude-module PySide6.QtDataVisualization \
	--exclude-module PySide6.QtGraphs \
	--exclude-module PySide6.Qt3DCore \
	--exclude-module PySide6.Qt3DRender \
	--exclude-module PySide6.Qt3DInput \
	--exclude-module PySide6.Qt3DLogic \
	--exclude-module PySide6.Qt3DAnimation \
	--exclude-module PySide6.Qt3DExtras \
	--exclude-module PySide6.QtSql \
	--exclude-module PySide6.QtTest \
	--exclude-module PySide6.QtXml \
	--exclude-module PySide6.QtOpenGL \
	--exclude-module PySide6.QtOpenGLWidgets \
	--exclude-module PySide6.QtSerialPort \
	--exclude-module PySide6.QtSerialBus \
	--exclude-module PySide6.QtBluetooth \
	--exclude-module PySide6.QtNfc \
	--exclude-module PySide6.QtPositioning \
	--exclude-module PySide6.QtLocation \
	--exclude-module PySide6.QtSensors \
	--exclude-module PySide6.QtRemoteObjects \
	--exclude-module PySide6.QtScxml \
	--exclude-module PySide6.QtStateMachine \
	--exclude-module PySide6.QtTextToSpeech \
	--exclude-module PySide6.QtVirtualKeyboard \
	--exclude-module PySide6.QtHelp \
	--exclude-module PySide6.QtUiTools \
	--exclude-module PySide6.QtDesigner \
	--exclude-module PySide6.QtDBus \
	--exclude-module PySide6.QtAxContainer \
	--exclude-module PySide6.QtAxServer \
	--exclude-module PySide6.QtHttpServer \
	--exclude-module PySide6.QtOpcUa \
	--exclude-module PySide6.QtSpatialAudio \
	--exclude-module tkinter \
	--exclude-module unittest \
	--exclude-module pydoc_data \
	--exclude-module ssl \
	--exclude-module _ssl

exe: dist/v6switch.exe

# 压掉 PyInstaller 的 INFO 刷屏（仅留 WARN+）；--log-level 在 6.22 仅 setLevel 子 logger，
# basicConfig 层面以 PYI_LOG_LEVEL 环境变量为准（export 对 cmd/sh recipe 环境均生效）
export PYI_LOG_LEVEL = WARN

dist/v6switch.exe: $(VENV)/Scripts/python.exe \
		$(wildcard app/v6switch/*.py) $(wildcard app/v6switch/bindings/*.py) app/run.py app/trim_pyside6.py app/pyproject.toml
	@echo TRIM PySide6
	$(Q)$(PY) app/trim_pyside6.py
	@echo PYINSTALLER $@
	$(Q)$(PY) -m PyInstaller --onefile --noconsole --name v6switch $(PI_LOGFLAGS) $(PI_EXCLUDES) \
		--paths app --specpath build --workpath build/pyinstaller --distpath dist \
		app/run.py

# ---- 测试：仅只读/参数拒绝类安全用例（网络变更类为人工测试） ----
test: dll $(VENV)/Scripts/python.exe
	$(PY) -m pytest tests/python -v

# 注意：clean 会清空 dist/（含运行时生成的 config.yaml，用户自定义 DNS64 会丢失）
# 不依赖 COMSPEC/sh（scoop make 环境下 COMSPEC 展开为空导致原实现必挂），
# 用系统 python 执行删除，任何 shell 下行为一致
clean:
	python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('dist', 'build', 'app/v6switch.egg-info', '.pytest_cache')]"
