"""PyInstaller 打包入口（exe 专用 launcher）。

不能用 src/esq_builder_mcp/__main__.py 直接当 PyInstaller 脚本——
相对导入在无包上下文中会炸；经绝对导入进入 server.main。
"""

from esq_builder_mcp.server import main

if __name__ == "__main__":
    main()
