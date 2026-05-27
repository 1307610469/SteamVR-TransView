VRChat VR 实时翻译悬浮 overlay
适用于 VRChat VR 玩家实时字幕翻译悬浮显示工具
基于 LiveCaptions 字幕数据库读取，在 VR 界面叠加显示翻译文字，解决 VR 模式下看不到实时翻译字幕的问题。
项目介绍
PC 端 VRChat 可直接用 LiveCaptions 看翻译，VR 头戴设备无法直接查看字幕。
本工具原理：
依赖 LiveCaptions-Translator 生成的翻译数据库
读取本地翻译历史数据库
通过 Steam 悬浮层 / OpenVR 叠加文字到 VR 画面中
实时展示聊天语音、文字的翻译内容
前置依赖
先安装部署：LiveCaptions-Translator
确保 LiveCaptions 正常运行并生成 translation_history.db 数据库
Windows 系统、已安装 SteamVR / VRChat VR 运行环境
使用方法
1. 路径配置
打开 steampy_overlay.py，修改数据库绝对路径为你自己的路径：
python
运行
# 修改这一行改成你本地的 translation_history.db 路径
self.db_path = Path(r"D:\livecap\translation_history.db")
2. 运行方式
直接运行打包好的程序：build/steampy_overlay.exe
也可本地 Python 运行 steampy_overlay.py 源码启动
3. 文件说明
plaintext
├── .idea/                # 项目配置
├── build/                # 打包输出目录
├── dist/                 # 打包分发目录
├── font/                 # 渲染所用字体文件
├── libopenvr_api_64.dll  # OpenVR 依赖库
├── steampy_overlay.py    # 主程序源码
├── temp_texture.png      # 悬浮层临时贴图资源
└── translation_history.db # LiveCaptions 翻译数据库
注意事项
代码内数据库为绝对路径，必须手动改成你自己 LiveCaptions 的存放路径
VR 模式需正常打开 SteamVR 再启动本工具
字体文件不要随意删除，否则无法正常渲染文字
仅适配 Windows 64 位，VR 头显通用 VRChat 场景
免责声明
本项目仅作学习交流使用，请勿用于违规游戏行为，使用风险自行承担。
