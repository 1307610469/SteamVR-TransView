# SteamVR-TransView
VRChat VR 实时翻译悬浮工具 | 语音/文字翻译实时叠加显示

## 功能介绍
- 读取 LiveCaptions 翻译数据库，实时获取翻译内容
- 通过 OpenVR/SteamVR 悬浮层在 VR 画面中叠加显示翻译文字
- 解决 VRChat VR 模式下无法查看语音翻译字幕的问题
- 轻量运行，不影响游戏性能

## 前置依赖
1. 安装并运行 [LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator)
2. 确保生成 `translation_history.db` 数据库文件
3. Windows 10/11 64位
4. 已安装 SteamVR 并正常运行

## 使用步骤
1. 启动 SteamVR 和 LiveCaptions-Translator
2. 运行脚本：`python steampy_overlay.py`
3. 在界面中选择本地的 `translation_history.db`
4. 点击“启动”后进入 VRChat VR，即可看到悬浮翻译

## 界面说明
- 默认使用轻量化 Tkinter 控制台，不额外引入新的 UI 依赖
- 左侧显示运行状态和最新翻译，右侧可切换数据库路径并控制启动/停止
- 底部日志会显示数据库监听和 SteamVR 初始化过程

## 命令行模式
- 如需只跑原始后台逻辑，可执行：`python steampy_overlay.py --cli`

## 文件说明
- `steampy_overlay.py`：主程序（OpenVR 悬浮渲染 + 数据库读取）
- `font/`：显示字体资源
- `libopenvr_api_64.dll`：VR 接口依赖库
- `translation_history.db`：翻译数据文件

## 注意事项
- 数据库路径建议选择本地实际文件，界面会自动保存本次启动路径
- 先启动 SteamVR，再运行本工具

