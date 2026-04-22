@echo off
chcp 65001 >nul
echo ========================================
echo   修复 PyInstaller 打包问题
echo ========================================
echo.

echo [1/6] 清理旧的构建文件...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist
if exist "*.spec" del /q *.spec
echo      ✓ 清理完成
echo.

echo [2/6] 清理 Python 缓存...
if exist "__pycache__" rmdir /s /q __pycache__
del /q /s *.pyc 2>nul
echo      ✓ 缓存清理完成
echo.

echo [3/6] 检查 Python 环境...
python --version
echo.

echo [4/6] 检查并安装兼容版本的依赖...
echo    安装 numpy==1.24.3...
pip install numpy==1.24.3 --quiet
echo    安装 pandas==2.0.3...
pip install pandas==2.0.3 --quiet
echo    安装 openpyxl...
pip install openpyxl --quiet
echo    升级 PyInstaller...
pip install --upgrade pyinstaller --quiet
echo      ✓ 依赖安装完成
echo.

echo [5/6] 执行打包...
echo.
pyinstaller --onefile --windowed --name "数据映射解析工具" ^
    --add-data "threat_type_config.json;." ^
    --add-data "threat_nomal.txt;." ^
    --add-data "对象.xlsx;." ^
    --hidden-import pandas._libs.interval ^
    --hidden-import pandas._libs.tslibs.base ^
    --hidden-import numpy._core._multiarray_umath ^
    --collect-all numpy ^
    --collect-all pandas ^
    main.py

echo.
echo [6/6] 打包完成！
echo.
if exist "dist\数据映射解析工具.exe" (
    echo ========================================
    echo   ✓ 打包成功！
    echo   可执行文件位置: dist\数据映射解析工具.exe
    echo ========================================
) else (
    echo ========================================
    echo   ✗ 打包失败，请检查错误信息
    echo ========================================
)

pause
