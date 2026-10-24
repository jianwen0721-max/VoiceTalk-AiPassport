<p align="right">  
  <strong>简体中文</strong> · <a href="README.md">English</a>  
</p>

# VoiceTalk (FoloToy AI Passport 应用)

<p align="center">  
  <a href="/LICENSE"><img src="https://img.shields.io/badge/许可证-MIT-64748b?style=flat-square" alt="MIT 许可证"></a>  
  <a href="#从源码构建"><img src="https://img.shields.io/badge/ESP--IDF-v5.5.3-14b8a6?style=flat-square" alt="ESP-IDF v5.5.3"></a>  
  <a href="#硬件"><img src="https://img.shields.io/badge/主控-ESP32--C3-2563eb?style=flat-square" alt="ESP32-C3"></a>  
  <a href="#从源码构建"><img src="https://img.shields.io/badge/界面-LVGL%209.5-f97316?style=flat-square" alt="LVGL 9.5"></a>  
</p>

VoiceTalk 把 [FoloToy AI Passport](https://github.com/FoloToy/ai-passport) 变成一台  
房间对讲机:同一个 6 位房号里的设备,按住 OK 就能互相说话。半双工是刻意的设计  
—— 同一时刻只有一个人发话,所以对讲不回声、不啸叫。

找得到对方的两种方式:

- **同一局域网** —— 设备用 UDP 广播互相发现。不要服务器、不要账号、不需要联网。
- **跨互联网** —— 在网页里填一台中转服务器的地址,设备通过它互通;地址解析不出来时设备**自动退回局域网**,通话不断,只是跨不了公网。

Wi-Fi 密码、房号、房间密码和中转服务器都在设备自己开的热点里用手机浏览器配置。  
不用装 App,也不用拿三个键去敲一个域名。

## 硬件

| 项目 | 参数                                               |
| -- | ------------------------------------------------ |
| 主板 | FoloToy AI Passport(ESP32-C3、8 MB Flash、无 PSRAM) |
| 屏幕 | 240 × 320 ST7789P3                               |
| 按键 | 三个键(UP / DOWN / OK),共用 GPIO0 的 ADC 阶梯            |
| 音频 | ES8311 codec,8 kHz / 16 bit / 单声道                |
| 固件 | ESP-IDF v5.5.3、LVGL 9.5,合并镜像从 `0x0` 刷写           |

## 怎么用

### 界面与按键

三页,硬派三键操作。

| 页面  | 怎么进       | 按键                                            |
| --- | --------- | --------------------------------------------- |
| 通话页 | 开机默认      | 按住 OK 发话,松开结束;短按 UP 进设置;短按 DOWN 看成员           |
| 成员页 | 通话页按 DOWN | 短按任意键回通话页                                     |
| 设置页 | 通话页按 UP   | UP/DOWN 移动,OK 进入编辑或执行;编辑态 UP/DOWN 改值,再按 OK 保存 |

通话页从上到下是:房号(主视觉)、链路色带(显示这通电话走互联网中转还是局域网,  
以及通不通)、20 段电平条(发话时取麦克风峰值,收听时取播放帧峰值,不是装饰动画)、  
状态字、发话区。

设置页里可以改亮度与音量,也能看传输方式、中转服务器地址(只读 —— 三个键敲不进  
域名)、以及还原出厂值。

### 网页设置

1. 设置页选「打开网页设置」,设备开一个开放热点 `VoiceTalk-XXXX`;
2. 手机连上这个热点,浏览器打开 `http://192.168.4.1`;
3. 填使用者名称、6 位房号、4 位房间密码(留空 = 开放房间)、要连的 Wi-Fi、  
   以及中转服务器地址与端口;
4. 保存后设备自动重启生效。

### 互联网通话

固件里没有写死服务器地址。地址在网页里填,可以是域名(`voice.example.com`)  
也可以是 IP。设备每 30 秒重新解析一次域名,所以 DDNS 换 IP 也能跟上;每 3 秒  
发一个探活包。这个探活包同时是 NAT 保活:设备一直在发,家用路由器才一直留着那条  
UDP 映射,服务器转回来的语音才进得来。

服务器上跑仓库自带的脚本:

```bash
python3 tools/voice_relay_server.py --port 8801 --passcode 2580
```

公网部署要点(脚本顶部注释里有完整版):

- 放通 **UDP** 端口 —— 这套协议只有 UDP;
- `--passcode` 一定要设 —— 服务器用与固件相同的算法算房间密钥,密码不对的设备进不了房间;
- 带宽按人头线性增长,一个人说话约 17 KB/s 上行;
- 语音**没有加密**。房间密码只是把 PCM 加扰成噪音,不是密码学意义的加密,别在上面说不能被机房听到的话。

常用参数:`--rooms`(房间白名单)、`--room`(单个房间)、`--max-clients`、  
`--allow-late-audio`、`--stats-interval`(秒)、`--privacy`(日志里隐藏客户端 IP)、  
`--verbose`。

## 从源码构建

```bash
# 1. 先激活 ESP-IDF v5.5.3(见 docs/development/engineering/environment-setup.zh_CN.md)
idf.py set-target esp32c3
idf.py build                       # -> build/FoloToy-AI-Passport.bin
idf.py merge-bin -o FoloToy-AI-Passport-full.bin
                                   # -> build/FoloToy-AI-Passport-full.bin,从 0x0 刷写
```

也可以直接跑仓库自带的验证门禁,它会一并产出并校验合并镜像:

```bash
./tools/validate.sh --static       # 仓库检查 + 主机测试
./tools/validate.sh --firmware     # 编译 + 合并镜像 + 布局校验
```

合并镜像是一个文件,从 `0x0` 一次性刷进去(里面已经包含 bootloader、分区表和  
应用程序):

```bash
python -m esptool --chip esp32c3 -b 460800 write_flash 0x0 build/FoloToy-AI-Passport-full.bin
```

从 `0x0` 刷写会覆盖整片 Flash,包括存放 Wi-Fi 与房间设置的 NVS 区域。

### 字体

LVGL 默认的 Montserrat 字体没有汉字。本应用随附一份生成的 Noto Sans SC 子集  
(`assets/fonts/app_font_16.c`)。如果你往界面里加了新的汉字,请把字加进  
`assets/fonts/app_font_symbols.txt` 再重新生成字体,否则屏上会显示方框。  
宿主测试 `tests/test_app_font_coverage.py` 会在 `main/app_ui.c` 用到某个字而子集里  
没有时直接判失败。

## 仓库结构

```text
main/                  应用:页面、状态、音频、网络、网页配网
components/bsp/        板级支持(显示、音频、按键、Wi-Fi、电源)
tools/                 验证、固件校验、中继服务器
tests/                 可在主机上跑的逻辑测试
assets/fonts/          生成的中文字体子集与字表
docs/reference/voicetalk/   应用档案(英文 + 简体中文)
```

板级逻辑留在 `components/bsp`;页面、状态机与应用任务放在 `main`。本应用的界面  
是从零写的,没有复用上游的 demo 菜单、页面或视觉外壳。

## 参与贡献

欢迎提 issue 和 PR。请先读  
[CONTRIBUTING.zh\_CN.md](/.github/CONTRIBUTING.zh_CN.md);安全相关问题请按  
[SECURITY.zh\_CN.md](/.github/SECURITY.zh_CN.md) 私下报告。本仓库遵循  
[行为准则](/.github/CODE_OF_CONDUCT.zh_CN.md)。

## 许可证

按 [MIT 许可证](/LICENSE) 发布。本项目是  
[FoloToy/ai-passport](https://github.com/FoloToy/ai-passport) 的衍生作品,上游同样是  
MIT;原始版权声明保留在 `LICENSE` 中,第三方声明列在 [NOTICE](/NOTICE)。

## 相关

- 应用档案(界面、协议、部署说明):[English](/docs/reference/voicetalk/README.md) · [简体中文](/docs/reference/voicetalk/README.zh_CN.md)
- 上游项目概览:[docs/README.zh\_CN.md](/docs/README.zh_CN.md)
- fork 工作流与根 README 归属:[docs/fork-guide.zh\_CN.md](/docs/fork-guide.zh_CN.md)
