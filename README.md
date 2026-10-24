<p align="right">  
  <a href="README.zh_CN.md">简体中文</a> · <strong>English</strong>  
</p>

# VoiceTalk Intercom for FoloToy AI Passport

<p align="center">  
  <a href="/LICENSE"><img src="https://img.shields.io/badge/License-MIT-64748b?style=flat-square" alt="MIT License"></a>  
  <a href="#building-from-source"><img src="https://img.shields.io/badge/ESP--IDF-v5.5.3-14b8a6?style=flat-square" alt="ESP-IDF v5.5.3"></a>  
  <a href="#hardware"><img src="https://img.shields.io/badge/Board-ESP32--C3-2563eb?style=flat-square" alt="ESP32-C3"></a>  
  <a href="#building-from-source"><img src="https://img.shields.io/badge/UI-LVGL%209.5-f97316?style=flat-square" alt="LVGL 9.5"></a>  
</p>

VoiceTalk turns the [FoloToy AI Passport](https://github.com/FoloToy/ai-passport)  
into a room intercom. Devices that share a 6-digit room number talk to each other  
by holding the OK button. It is half duplex on purpose: only one person transmits  
at a time, so there is no echo and no feedback howl.

A peer can be reached in two ways:

- **Same LAN** — devices find each other by UDP broadcast. No server, no account, no internet access required.
- **Across the internet** — enter a relay server address on the web page and devices reach each other through it. If the address cannot be resolved, the device falls back to LAN automatically and calling keeps working, just without crossing the public internet.

Wi-Fi credentials, room number, room password and the relay server are all set  
from a phone browser on the device's own access point. There is no companion app  
to install, and the device never asks you to type a domain name with three  
buttons.

## Hardware

| Item     | Value                                                   |
| -------- | ------------------------------------------------------- |
| Board    | FoloToy AI Passport (ESP32-C3, 8 MB Flash, no PSRAM)    |
| Display  | 240 x 320 ST7789P3                                      |
| Input    | Three buttons (UP / DOWN / OK) on one ADC ladder, GPIO0 |
| Audio    | ES8311 codec, 8 kHz / 16-bit mono                       |
| Firmware | ESP-IDF v5.5.3, LVGL 9.5, merged image flashed at `0x0` |

## Using it

### Screens and keys

Three screens, three keys.

| Screen   | How to reach it         | Keys                                                                                    |
| -------- | ----------------------- | --------------------------------------------------------------------------------------- |
| Talk     | default at boot         | Hold OK to talk, release to stop. Short UP opens settings. Short DOWN shows members.    |
| Members  | DOWN on the talk screen | Any short press returns to talk.                                                        |
| Settings | UP on the talk screen   | UP/DOWN moves, OK edits or runs. While editing, UP/DOWN changes the value and OK saves. |

The talk screen reads top to bottom: the room number as the hero element, a link  
ribbon that shows whether the call is going through the internet relay or the LAN  
and whether it is up, a 20-segment level meter driven by real audio peaks (the  
microphone while transmitting, the played frame while receiving — not decorative  
animation), a status line, and the talk area.

Settings exposes brightness, volume, transport mode, the relay server address  
(read-only, because a domain cannot be typed with three buttons) and factory  
reset.

### Web setup

1. Pick **open web setup** on the settings screen. The device opens an open AP named `VoiceTalk-XXXX`.
2. Join that AP from a phone and browse to `http://192.168.4.1`.
3. Fill in your name, the 6-digit room number, a 4-digit room password (empty means an open room), the Wi-Fi to join, and the relay server host and port.
4. Saving reboots the device.

### Calling over the internet

The firmware has no hard-coded server address. It comes from the web page and may  
be a domain (`voice.example.com`) or an IP. The device re-resolves the name every  
30 seconds, so a DDNS address that changes IP keeps working, and sends a probe  
every 3 seconds. That probe is also the NAT keepalive: because the device keeps  
transmitting, a home router keeps the UDP mapping open and relayed audio can come  
back in.

Run the relay server that ships with this repository:

```bash
python3 tools/voice_relay_server.py --port 8801 --passcode 2580
```

Checklist for a public deployment (also documented at the top of the script):

- Open the **UDP** port; the protocol is UDP only.
- Always pass `--passcode`. The server derives the room key with the same algorithm as the firmware, so a device with the wrong password cannot join the room.
- Bandwidth grows linearly with the number of speakers: roughly 17 KB/s upstream per speaking person.
- Audio packets are **not encrypted**. The passcode scrambles PCM so a wrong password sounds like noise; it is not cryptography. Do not say anything over it that you would not say in front of the server operator.

Useful flags: `--rooms` (room allowlist), `--room` (single room), `--max-clients`,  
`--allow-late-audio`, `--stats-interval` (seconds), `--privacy` (mask client IPs in  
logs) and `--verbose`.

## Building from source

```bash
# 1. Activate ESP-IDF v5.5.3 (see docs/development/engineering/environment-setup.md)
idf.py set-target esp32c3
idf.py build                       # -> build/FoloToy-AI-Passport.bin
idf.py merge-bin -o FoloToy-AI-Passport-full.bin
                                   # -> build/FoloToy-AI-Passport-full.bin, flash at 0x0
```

Or run the repository's own validation gate, which also produces and verifies the  
merged image:

```bash
./tools/validate.sh --static       # repository checks + host tests
./tools/validate.sh --firmware     # build + merged image + layout verification
```

Flash the merged image as a single file at offset `0x0` (it already contains the  
bootloader, the partition table and the application):

```bash
python -m esptool --chip esp32c3 -b 460800 write_flash 0x0 build/FoloToy-AI-Passport-full.bin
```

Flashing at `0x0` overwrites the whole Flash, including the NVS area that holds  
your Wi-Fi and room settings.

### Fonts

The default LVGL Montserrat fonts carry no Chinese glyphs. This application ships  
a generated Noto Sans SC subset (`assets/fonts/app_font_16.c`). If you add Chinese  
text to the UI, add the characters to `assets/fonts/app_font_symbols.txt` and  
regenerate the font, otherwise the panel shows boxes. The host test  
`tests/test_app_font_coverage.py` fails the build when a character used by  
`main/app_ui.c` is missing from the subset.

## Repository layout

```text
main/                  application: pages, state, audio, network, web setup
components/bsp/        board support (display, audio, buttons, Wi-Fi, power)
tools/                 validation, firmware verification, relay server
tests/                 host-runnable logic tests
assets/fonts/          generated CJK font subset and its symbol list
docs/reference/voicetalk/   application archive (English + Simplified Chinese)
```

Board logic stays in `components/bsp`; pages, state machines and application tasks  
live in `main`. The UI of this application is written from scratch and does not  
reuse the upstream demo menu, screens, or visual shell.

## Contributing

Bug reports, feature requests and pull requests are welcome. Please read  
[CONTRIBUTING.md](/.github/CONTRIBUTING.md) first, and report security issues  
privately as described in [SECURITY.md](/.github/SECURITY.md). This repository  
follows the [Code of Conduct](/.github/CODE_OF_CONDUCT.md).

## License

Released under the [MIT License](/LICENSE). This project is a derivative work of  
[FoloToy/ai-passport](https://github.com/FoloToy/ai-passport), which is also MIT  
licensed; the original copyright notice is preserved in `LICENSE` and third-party  
notices are listed in [NOTICE](/NOTICE).

## Related

- Application archive (screens, protocol, deployment notes): [English](/docs/reference/voicetalk/README.md) · [简体中文](/docs/reference/voicetalk/README.zh_CN.md)
- Upstream project overview: [docs/README.md](/docs/README.md)
- Fork workflow and root README ownership: [docs/fork-guide.md](/docs/fork-guide.md)
