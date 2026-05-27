# vrc_trans.py
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
1. 打开 `steampy_overlay.py`
2. 修改数据库路径为你本地的 `translation_history.db` 绝对路径
3. 运行脚本：`python steampy_overlay.py`
4. 进入 VRChat VR 即可看到悬浮翻译

## 文件说明
- `steampy_overlay.py`：主程序（OpenVR 悬浮渲染 + 数据库读取）
- `font/`：显示字体资源
- `libopenvr_api_64.dll`：VR 接口依赖库
- `translation_history.db`：翻译数据文件

## 注意事项
- 数据库路径必须填写**绝对路径**，否则无法读取翻译
- 先启动 SteamVR，再运行本工具
- 仅用于个人学习交流，请勿违规使用

## 许可证
MIT
