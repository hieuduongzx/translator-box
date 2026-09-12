# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — onedir, windowed. Chạy từ gốc repo:

    pyinstaller packaging/ScreenTranslator2K.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(SPECPATH)
if os.path.basename(ROOT) == "packaging":
    ROOT = os.path.dirname(ROOT)
APP = os.path.join(ROOT, "python-app")
ICON = os.path.join(APP, "assets", "icon.ico")
VERSION_FILE = os.path.join(ROOT, "packaging", "file_version_info.txt")

# Chỉ gom file config/dict/font của rapidocr (KHÔNG collect_submodules — nó sẽ
# kéo theo backend torch/paddle nặng hàng GB mà app không dùng).
datas = [(os.path.join(APP, "assets"), "assets")]
datas += collect_data_files("rapidocr")
datas += collect_data_files("onnxruntime")

binaries = collect_dynamic_libs("onnxruntime")

# App chỉ dùng backend ONNX Runtime; engine được nạp động nên phải khai hiddenimport.
# `pyperclip` được nạp qua importlib.import_module (services._require) và
# `keyboard`/`mouse` nằm trong try/except — phân tích tĩnh của PyInstaller không
# thấy chắc chắn cả ba, nên khai báo tường minh. Thiếu chúng thì bản đóng gói vẫn
# chạy nhưng dịch văn bản chọn / phím tắt / chuột phải sẽ hỏng khi người dùng bấm.
hiddenimports = [
    "rapidocr",
    "rapidocr.inference_engine.onnxruntime",
    "rapidocr.inference_engine.onnxruntime.main",
    "rapidocr.inference_engine.onnxruntime.provider_config",
    "onnxruntime",
    "cv2",
    "numpy",
    "PIL",
    "pyperclip",
    "keyboard",
    "mouse",
] + (
    [
        # Windows OCR nạp bốn namespace này bằng `import` bên trong hàm; khai báo
        # tường minh vì phân tích tĩnh không lần được qua namespace package.
        "winsdk",
        "winsdk.windows.globalization",
        "winsdk.windows.graphics.imaging",
        "winsdk.windows.media.ocr",
        "winsdk.windows.storage",
        # Thu âm thanh hệ thống (WASAPI loopback) — import lười trong soniox.
        "pyaudiowpatch",
    ]
    if os.name == "nt"
    else []
)

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pytest",
        "torch",
        "torchvision",
        "torchaudio",
        "paddle",
        "paddlepaddle",
        "paddlex",
        "paddleocr",
        "tensorboard",
        "tensorrt",
        "scipy",
        "pandas",
        "rapidocr.inference_engine.pytorch",
        "rapidocr.inference_engine.paddle",
        "rapidocr.inference_engine.mnn",
        "rapidocr.inference_engine.tensorrt",
        "PySide6.QtWebEngineCore",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScreenTranslator2K",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON if os.path.exists(ICON) else None,
    version=VERSION_FILE if os.path.exists(VERSION_FILE) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ScreenTranslator2K",
)
