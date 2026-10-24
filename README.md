[简体中文](README.zh_CN.md)

# VoiceTalk Intercom (AI Passport application)

Turns the AI Passport into a room intercom: devices that share a 6-digit room  
number talk by holding OK. It is half duplex on purpose - only one person speaks  
at a time, so there is no echo and no feedback howl. Devices on the same LAN  
reach each other directly; with a relay server configured they also reach each  
other across the internet.

## Screens and keys

Three screens, three keys:

| Screen   | How to reach it         | Keys                                                                                  |
| -------- | ----------------------- | ------------------------------------------------------------------------------------- |
| Talk     | default at boot         | hold OK to talk, release to stop; short UP opens settings; short DOWN shows members   |
| Members  | DOWN on the talk screen | any short press returns to talk                                                       |
| Settings | UP on the talk screen   | UP/DOWN moves, OK edits or runs; while editing UP/DOWN changes the value and OK saves |

The talk screen reads top to bottom: room number (the hero element), a link  
ribbon (internet relay or LAN, and whether it is up), a level meter driven by  
real audio peaks - the microphone while talking, the played frame while  
listening, not decorative animation - a status line, and the talk area. Settings  
exposes brightness, volume, transport mode, the relay server address and the  
factory reset. The server address is display-only: a domain cannot be typed with  
three buttons, so it is edited on the web page.

## Web setup (Wi-Fi and room)

1. Pick "open web setup" on the settings screen; the device opens an open AP  
   named `VoiceTalk-XXXX`.
2. Join that AP from a phone and browse to `http://192.168.4.1`.
3. Fill in your name, the 6-digit room, a 4-digit room password (empty means an  
   open room), the Wi-Fi to join, and the relay server host and port.
4. Saving reboots the device.

## Calling over the internet

The firmware has no hard-coded server address - it comes from the web page and  
may be a domain (for example `voice.example.com`) or an IP. The device  
re-resolves the name every 30 s (so a DDNS change is picked up) and probes every  
3 s. That probe doubles as NAT keepalive: while the device keeps sending, a home  
router keeps the UDP mapping, so relayed audio can come back in.

If the name does not resolve, the device reports "address resolution failed" and  
**falls back to LAN broadcast** - calls keep working, they just cannot cross the  
public internet. Leaving the address empty is exactly the pure-LAN mode.

Run the bundled [`tools/voice_relay_server.py`](../../../tools/voice_relay_server.py)  
on the server:

```bash
python3 tools/voice_relay_server.py --port 8801 --passcode 2580
```

For a public deployment (see the header comment in that script): open the **UDP**  
port, always pass `--passcode` so the server can verify room keys with the same  
algorithm the firmware uses, and budget about 17 KB/s upstream per speaker.  
Frames are scrambled, not encrypted - do not treat the relay as a private line.

## Protocol

`main/app_protocol.h` defines a 16-byte big-endian header (`VT` magic, version,  
type, room, sender, sequence, length, flags) over 8 kHz / 16-bit mono audio in  
20 ms frames (320 bytes). HELLO joins and heartbeats every 2 s, DISCOVER looks  
for a server, SERVER_HERE answers it, AUDIO and AUDIO_END carry speech. Rooms  
with a password scramble the PCM with the room key - enough that a wrong  
password sounds like noise, not encryption.

## Build and flash

```bash
./tools/validate.sh --static     # repository checks plus host tests
./tools/validate.sh --firmware   # build plus the merged 0x0 image
```

`build/FoloToy-AI-Passport-full.bin` flashes from `0x0` and contains the  
bootloader, the partition table and the application. `tests/test_app_font_coverage.py`  
keeps the UI honest: every Chinese character drawn on screen must exist in  
`assets/fonts/app_font_symbols.txt`, otherwise it renders as a blank box.
