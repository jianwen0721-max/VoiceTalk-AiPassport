#!/usr/bin/env python3
"""群组通话的 UDP 中转服务器(「服务器中转」传输模式的对端)。

设备上的「服务器中转」模式把每个线路包发往本进程,本进程再转发给同一房间里
的其他设备,从而跨网段/跨路由器互通。协议与固件一致,见 main/app_protocol.h:

    0      1      2        3      4       8       10      12      14      16
    +------+------+--------+------+-------+-------+-------+-------+-------+
    | 'V'  | 'T'  | version| type | room  | sender| seq   | len   | flags |
    +------+------+--------+------+-------+-------+-------+-------+-------+
    大端,16 字节头 + len 字节载荷

v2 相对 v1 的变化:房间号从 2 字节扩到 4 字节(需求要求 6 位十进制房号),
新增 flags 与 DISCOVER / SERVER_HERE(设备用广播找服务器,不用手填地址)。
v1 固件与本版本不互通,两边的设备要一起升级。

只做转发,不解码语音,也不改动包内容 —— 服务器不参与业务,便于排障。

用法(局域网):
    python3 tools/voice_relay_server.py --port 8801
    python3 tools/voice_relay_server.py --port 8801 --room 123456

用法(公网):
    python3 tools/voice_relay_server.py --port 8801 --passcode 2580
    python3 tools/voice_relay_server.py --port 8801 --rooms 123456,234567 \\
        --passcode 2580 --max-clients 64 --stats-interval 300

—— 公网部署要点 ——
1. 放通 UDP(不是 TCP)。云厂商安全组 + 系统防火墙都要开,例如
   `ufw allow 8801/udp`。
2. 房间密码一定要设:带 `--passcode` 时服务器会用与固件相同的算法算出每个
   房间的密钥,密钥对不上的 HELLO 直接拒掉,陌生人就算猜到房号也进不来。
   不设 `--passcode` 时退化为"房间里第一个上线的人把密钥钉住",能防
   半路插进来的人,但防不住抢先占房的人 —— 公网请务必设密码。
3. 设备每 3 秒向服务器发一次 DISCOVER 探活,这条上行流量就是 NAT 打洞:
   服务器回包走的是同一条映射,所以设备不需要端口映射,也不要在 NAT 后面
   再套一层会改端口的代理。
4. 上行带宽按人头线性增长:每人说话时约 50 包/秒 × 336 字节 ≈ 17 KB/s,
   一个 4 人房间同时只有 1 人在说,约 17 KB/s 上行 + 51 KB/s 下行。
5. 进程本身无状态,房间里没人时内存会自己清空;重启最多打断 2 秒
   (设备的 HELLO 心跳是 2 秒一发)。

注意:线路包没有加密(房间密钥只是"让密码不对的人听不懂"的轻量加扰),
中转服务器能看到明文 UDP 内容。公网部署时请把它当成"公开的电话线",
别在上面说不能让运营商/机房听到的话;需要真保密请走 VPN 或加密隧道。
"""
from __future__ import annotations

import argparse
import logging
import socket
import sys
import time

# 与 main/app_protocol.h 保持一致。
MAGIC0 = 0x56
MAGIC1 = 0x54
VERSION = 2
HEADER_SIZE = 16
MAX_PAYLOAD = 320

PKT_HELLO = 1
PKT_BYE = 2
PKT_AUDIO = 3
PKT_AUDIO_END = 4
PKT_DISCOVER = 5
PKT_SERVER_HERE = 6

FLAG_ENCRYPTED = 0x0001

# 客户端多久没再发包就认为离线(要比固件的心跳间隔 2 秒宽松一些)。
CLIENT_TTL_S = 10.0
# 单个来源 IP 每秒最多转发多少包,防止异常设备/扫描器把带宽打满。
# 20 ms 一帧 = 50 包/秒,给到 200 包/秒留足余量。
RATE_LIMIT_PER_S = 200
# 单个来源 IP 每秒最多应答几次 DISCOVER。DISCOVER 16 字节、SERVER_HERE 18 字节,
# 放大倍数很小,但仍然限速,免得被拿来当反射源。
DISCOVER_LIMIT_PER_S = 2
# 内存上限:房间数与人数都要封顶,公网上的随机包不能把进程撑爆。
# 每房间人数与固件的 VT_ROOM_MAX_MEMBERS 对齐。
MAX_ROOMS = 64
MAX_CLIENTS_PER_ROOM = 32
MAX_TOTAL_CLIENTS = 256
# 清理过期成员的周期(不用每个包都扫一遍表)。
SWEEP_INTERVAL_S = 1.0
# 公网跑的时候想看进程还活着,就让它定期报一次数;0 = 不报。
MIN_PACKET_BYTES = HEADER_SIZE


def room_key(room: int, passcode: int, has_pass: bool) -> int:
    """与 main/app_protocol.c 的 vt_room_key 逐位一致的 Python 版本。

    必须一模一样,否则服务器会把密码正确的设备当成密码错误拒掉。
    """
    if not has_pass:
        return 0
    h = 0x811C9DC5
    for shift in (0, 8, 16):
        h ^= (room >> shift) & 0xFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    for shift in (0, 8):
        h ^= (passcode >> shift) & 0xFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    return 1 if h == 0 else h


def decode(buf: bytes) -> tuple[int, int, int, int, int, int] | None:
    """解析包头,返回 (type, room, sender, seq, length, flags);不是合法包返回 None。"""
    if len(buf) < HEADER_SIZE:
        return None
    if buf[0] != MAGIC0 or buf[1] != MAGIC1:
        return None
    if buf[2] != VERSION:
        return None
    pkt_type = buf[3]
    room = int.from_bytes(buf[4:8], "big")
    sender = int.from_bytes(buf[8:10], "big")
    seq = int.from_bytes(buf[10:12], "big")
    length = int.from_bytes(buf[12:14], "big")
    flags = int.from_bytes(buf[14:16], "big")
    if length > MAX_PAYLOAD:
        return None
    if len(buf) < HEADER_SIZE + length:
        return None
    return pkt_type, room, sender, seq, length, flags


def encode(pkt_type: int, room: int, sender: int, seq: int, flags: int,
           payload: bytes = b"") -> bytes:
    """按固件格式组一个包(目前只有 SERVER_HERE 需要服务器主动发包)。"""
    header = bytes([MAGIC0, MAGIC1, VERSION, pkt_type & 0xFF])
    header += room.to_bytes(4, "big")
    header += sender.to_bytes(2, "big")
    header += seq.to_bytes(2, "big")
    header += len(payload).to_bytes(2, "big")
    header += flags.to_bytes(2, "big")
    return header + payload


class RateLimiter:
    """按来源 IP 计数的滑动窗口限速器,窗口外的记录会被清掉,不会无限增长。"""

    def __init__(self, sweep_interval: float = SWEEP_INTERVAL_S) -> None:
        self._hits: dict[str, list[float]] = {}
        self._sweep_interval = sweep_interval
        self._last_sweep = time.monotonic()

    def allow(self, key: str, now: float, limit: int, window: float = 1.0) -> bool:
        if limit <= 0:
            return True
        window_hits = self._hits.setdefault(key, [])
        # 定期清理,免得公网上的随机源把字典撑大。
        if now - self._last_sweep > self._sweep_interval:
            self._last_sweep = now
            for k in list(self._hits):
                if not self._hits[k] or now - self._hits[k][-1] > window:
                    del self._hits[k]
        window_hits[:] = [t for t in window_hits if now - t < window]
        if len(window_hits) >= limit:
            return False
        window_hits.append(now)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="VoiceTalk UDP 群组通话中转服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址,默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8801, help="监听端口,默认 8801")
    parser.add_argument("--room", type=int, default=None,
                        help="只服务指定房间号(6 位十进制),默认不限")
    parser.add_argument("--rooms", default=None,
                        help="房间白名单,逗号分隔,例如 123456,234567;与 --room 二选一")
    parser.add_argument("--passcode", default=None,
                        help="房间密码(4 位数字)。给了就按固件算法校验每个房间的密钥, "
                             "公网部署必填")
    parser.add_argument("--max-clients", type=int, default=MAX_TOTAL_CLIENTS,
                        help=f"同时在册的客户端总数上限,默认 {MAX_TOTAL_CLIENTS}")
    parser.add_argument("--allow-late-audio", action="store_true",
                        help="允许没打过招呼就发语音(默认要求先收到 HELLO)")
    parser.add_argument("--stats-interval", type=float, default=0.0,
                        help="每隔多少秒打印一次在线统计,0 = 不打,默认 0")
    parser.add_argument("--privacy", action="store_true",
                        help="日志里的 IP 只打印前两段(公网长期留日志时有用)")
    parser.add_argument("--verbose", action="store_true", help="打印每个包的转发明细")
    args = parser.parse_args()

    rooms_allowed: set[int] | None = None
    if args.rooms:
        rooms_allowed = set()
        for text in args.rooms.split(","):
            text = text.strip()
            if text:
                rooms_allowed.add(int(text))
    elif args.room is not None:
        rooms_allowed = {args.room}

    expected_key_for = None
    if args.passcode is not None:
        code = args.passcode.strip()
        if len(code) != 4 or not code.isdigit():
            parser.error("--passcode 必须是 4 位数字")
        passcode = int(code)
        expected_key_for = lambda room: room_key(room, passcode, True)  # noqa: E731

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("voice-relay")

    def show(addr: tuple[str, int]) -> str:
        if not args.privacy:
            return f"{addr[0]}:{addr[1]}"
        host = addr[0].split(".")
        if len(host) == 4:
            return f"{host[0]}.{host[1]}.*.*:{addr[1]}"
        return f"{addr[0]}:{addr[1]}"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # 公网上会有扫描噪声,给接收缓冲留点余地,免得突发丢包。
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 18)
    except OSError:
        pass
    sock.bind((args.host, args.port))
    log.info("监听 %s:%d(房间限制: %s,密钥校验: %s)",
             args.host, args.port,
             "不限" if rooms_allowed is None else
             ",".join(f"{r:06d}" for r in sorted(rooms_allowed)),
             "按 --passcode 严格校验" if expected_key_for else "按房间首个上线者钉住")

    # room -> sender -> [addr, last_seen, name, key]
    clients: dict[int, dict[int, list]] = {}
    # room -> 被钉住的房间密钥(只有没给 --passcode 时才用)
    pinned_keys: dict[int, int] = {}
    rates = RateLimiter()
    last_sweep = time.monotonic()
    last_stats = time.monotonic()
    dropped_unknown = 0
    dropped_rate = 0

    def total_clients() -> int:
        return sum(len(peers) for peers in clients.values())

    def sweep(now: float) -> None:
        for room in list(clients):
            for sender in list(clients[room]):
                if now - clients[room][sender][1] > CLIENT_TTL_S:
                    log.info("房间 %06d: %s(%04x) 超时离开", room,
                             clients[room][sender][2] or "?", sender)
                    del clients[room][sender]
            if not clients[room]:
                del clients[room]
                pinned_keys.pop(room, None)

    while True:
        try:
            buf, addr = sock.recvfrom(HEADER_SIZE + MAX_PAYLOAD + 64)
        except KeyboardInterrupt:
            log.info("退出")
            return 0

        parsed = decode(buf)
        if parsed is None:
            continue
        pkt_type, room, sender, seq, length, flags = parsed
        payload = buf[HEADER_SIZE:HEADER_SIZE + length]
        now = time.monotonic()

        if rooms_allowed is not None and room not in rooms_allowed:
            continue

        # 先按来源 IP 限速,再做任何别的事 —— 公网上的噪声不该消耗表项。
        if not rates.allow(addr[0], now, RATE_LIMIT_PER_S):
            dropped_rate += 1
            if dropped_rate % 200 == 1:
                log.warning("来源 %s 发包过快,已累计丢弃 %d 包", show(addr), dropped_rate)
            continue

        # 设备探活/找服务器:回一个 SERVER_HERE(载荷 = 本服务端口)。
        # 这条回包同时是设备侧判断"服务器在线"的依据,也是 NAT 保活的另一半。
        if pkt_type == PKT_DISCOVER:
            if rates.allow(f"d:{addr[0]}", now, DISCOVER_LIMIT_PER_S):
                sock.sendto(encode(PKT_SERVER_HERE, room, 0, 0, 0,
                                   args.port.to_bytes(2, "big")), addr)
                log.debug("应答 DISCOVER -> %s", show(addr))
            continue

        if pkt_type == PKT_HELLO:
            name = ""
            key = 0
            if length >= 5:
                name_len = payload[0]
                if 1 + name_len + 4 <= length:
                    name = payload[1:1 + name_len].decode("utf-8", "replace")
                    key = int.from_bytes(payload[1 + name_len:5 + name_len], "big")
            elif length == 4:
                key = int.from_bytes(payload[0:4], "big")

            if expected_key_for is not None:
                if key != expected_key_for(room):
                    log.warning("房间 %06d: %s 的 HELLO 密钥不对,拒绝", room, show(addr))
                    continue
            else:
                pinned = pinned_keys.get(room)
                if pinned is None:
                    pinned_keys[room] = key
                elif key != pinned:
                    log.warning("房间 %06d: %s 的 HELLO 密钥与房内其他人不符,拒绝",
                                room, show(addr))
                    continue

            table = clients.setdefault(room, {})
            if sender not in table and len(table) >= MAX_CLIENTS_PER_ROOM:
                log.warning("房间 %06d 已满(%d 人),拒绝 %s",
                            room, MAX_CLIENTS_PER_ROOM, show(addr))
                continue
            if sender not in table and total_clients() >= args.max_clients:
                log.warning("在册客户端已达上限 %d,拒绝 %s", args.max_clients, show(addr))
                continue
            if sender not in table and len(clients) >= MAX_ROOMS and room not in clients:
                log.warning("房间数已达上限 %d,拒绝新房间 %06d", MAX_ROOMS, room)
                continue

            if sender not in table:
                log.info("房间 %06d: %s(%04x) 上线,来自 %s",
                         room, name or "?", sender, show(addr))
            table[sender] = [addr, now, name, key]
            continue

        if pkt_type == PKT_BYE:
            if room in clients and sender in clients[room]:
                log.info("房间 %06d: %s(%04x) 下线", room,
                         clients[room][sender][2] or "?", sender)
                del clients[room][sender]
                if not clients[room]:
                    del clients[room]
                    pinned_keys.pop(room, None)
            continue

        if pkt_type not in (PKT_AUDIO, PKT_AUDIO_END):
            continue

        table = clients.get(room)
        entry = table.get(sender) if table else None
        if entry is None:
            # 没打过招呼就发语音:默认丢掉。公网上这条很重要 —— 否则任何人
            # 只要知道房号和 sender id 就能往房间里灌声音。
            # 正常设备 2 秒一发 HELLO,最多卡 2 秒就能恢复。
            if not args.allow_late_audio:
                dropped_unknown += 1
                if dropped_unknown % 50 == 1:
                    log.warning("房间 %06d: 来自 %s 的未知 sender %04x,已累计丢弃 %d 包",
                                room, show(addr), sender, dropped_unknown)
                continue
            if table is None:
                if len(clients) >= MAX_ROOMS:
                    continue
                table = clients.setdefault(room, {})
            if len(table) >= MAX_CLIENTS_PER_ROOM:
                continue
            table[sender] = [addr, now, "", 0]
            entry = table[sender]
        else:
            # 地址变了(NAT 重绑)只允许在 HELLO 里改,语音包改地址视为伪造。
            if tuple(entry[0]) != tuple(addr):
                log.warning("房间 %06d: sender %04x 的地址从 %s 变成 %s,语音包不认",
                            room, sender, show(tuple(entry[0])), show(addr))
                continue
            entry[1] = now

        if pkt_type == PKT_AUDIO:
            if not rates.allow(f"a:{room}:{sender}", now, RATE_LIMIT_PER_S):
                log.warning("房间 %06d: %04x 发包过快,丢弃一帧", room, sender)
                continue
            if (flags & FLAG_ENCRYPTED) == 0 and pinned_keys.get(room, 0) != 0:
                # 房间是带密码的,却收到未加扰的语音:多半是密码不对的设备。
                log.warning("房间 %06d: %04x 的语音没有加扰标志,丢弃", room, sender)
                continue

        for peer, peer_entry in table.items():
            if peer == sender:
                continue
            sock.sendto(buf, peer_entry[0])

        if now - last_sweep >= SWEEP_INTERVAL_S:
            last_sweep = now
            sweep(now)
        if args.stats_interval > 0 and now - last_stats >= args.stats_interval:
            last_stats = now
            log.info("统计: %d 个房间, %d 人在册, 已丢弃未知来源 %d 包 / 超速 %d 包",
                     len(clients), total_clients(), dropped_unknown, dropped_rate)


if __name__ == "__main__":
    sys.exit(main())
