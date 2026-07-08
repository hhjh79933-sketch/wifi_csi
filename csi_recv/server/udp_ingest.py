#!/usr/bin/env python3
"""用于接收 ESP32 CSI 事件的 UDP 采集脚本。

它的职责很简单：
1. 监听指定 UDP 端口，接收来自设备的上报。
2. 尝试把收到的文本解析成 JSON；如果不是合法 JSON，也保留原始内容。
3. 把每条消息整理成一行 JSON 写入文件，形成 JSONL 日志，方便后续分析。

建议运行在公网服务器（例如 ECS）上。请通过防火墙或安全组限制访问，
只开放你真正需要的 UDP 端口，避免被无关流量打扰。
"""

import argparse
import binascii
import json
import socket
import struct
import sys
import time
from typing import Any, Dict, Optional, List, Tuple


def _now_ms() -> int:
    # 返回当前时间戳的毫秒数，便于日志记录和跨系统对齐。
    return int(time.time() * 1000)


# ── CSI 二进制协议常量 ───────────────────────────────────────────
# ESP32 端 csi_raw_pkt_hdr_t（小端序打包，sendto 直接发送内存字节）：
#   uint32 magic   = 0x43534921 → wire: 21 49 53 43
#   uint16 version = 1          → wire: 01 00
#   uint32 seq
#   uint32 t_ms
#   uint8  src_mac[6]
#   int8   rssi
#   uint16 csi_len              → 后续 csi_len 字节为 CSI raw data
_CSI_HDR_FMT = "<IHI6sbH"  # little-endian unpack 格式
_CSI_HDR_SIZE = struct.calcsize(_CSI_HDR_FMT)  # 23 字节
_CSI_MAGIC_WIRE = b"\x21\x49\x53\x43"  # 0x43534921 on wire (LE)


def _try_parse_csi_binary(
    data: bytes,
) -> Optional[Tuple[int, int, int, str, int, bytes]]:
    """尝试按 CSI 二进制协议解析。

    若 data 前 4 字节匹配魔数且长度足够，返回：
        (version, seq, t_ms, mac_str, rssi, csi_data)
    否则返回 None。
    """
    if len(data) < _CSI_HDR_SIZE:
        return None
    if data[:4] != _CSI_MAGIC_WIRE:
        return None

    version, seq, t_ms, mac_raw, rssi, csi_len = struct.unpack_from(
        _CSI_HDR_FMT, data, 0
    )
    mac_str = "%02x:%02x:%02x:%02x:%02x:%02x" % tuple(mac_raw)

    payload_start = _CSI_HDR_SIZE
    payload_end = payload_start + csi_len
    if payload_end > len(data):
        # 实际收到的数据比声明的 csi_len 短，截断补 0
        csi_data = data[payload_start:] + b"\x00" * (payload_end - len(data))
    else:
        csi_data = data[payload_start:payload_end]

    return (version, seq, t_ms, mac_str, rssi, csi_data)


def _safe_json_loads(text: str) -> Optional[Dict[str, Any]]:
    # 尝试把字符串解析为 JSON。
    # 解析失败时返回 None；如果顶层不是对象，也包装成字典，方便后续统一处理。
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else {"_": obj}


def main(argv: Optional[List[str]] = None) -> int:
    # 参数用于控制监听地址、端口、输出文件和是否把结果打印到终端。
    parser = argparse.ArgumentParser(description="UDP JSON ingest (hb/csi_evt)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=3333, help="UDP port (default: 3333)")
    parser.add_argument(
        "--out",
        default="events.jsonl",
        help="Output file path for JSONL (default: events.jsonl)",
    )
    parser.add_argument(
        "--csi-out",
        default=None,
        help="Optional: separate file for raw CSI hex dumps (one hex line per frame)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Also print parsed events to stdout",
    )
    args = parser.parse_args(argv)

    # 绑定一个 UDP socket，监听指定地址/端口，接收任何发送端发来的数据报。
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.bind, args.port))

    # 把启动信息打印到 stderr，和正常的数据输出区分开。
    sys.stderr.write(f"[udp_ingest] listening on {args.bind}:{args.port}, out={args.out}\n")
    sys.stderr.flush()

    # 以追加方式写入文件，程序重启后不会覆盖历史数据；
    # 每写一条就刷新一次，保证实时采集时能立刻在磁盘上看到内容。

    # 可选的 CSI hex 独立文件（一行一帧，空格分隔：recv_ts seq t_ms mac rssi hex）
    csi_fp = None
    if args.csi_out is not None:
        csi_fp = open(args.csi_out, "a", encoding="ascii")
        sys.stderr.write(f"[udp_ingest] CSI hex dump -> {args.csi_out}\n")
        sys.stderr.flush()

    try:
        with open(args.out, "a", encoding="utf-8") as fp:
            while True:
                # 一次 recvfrom 对应一个 UDP 包；8192 字节是接收缓冲区上限。
                # 如果实际包更大，超出部分会被截断，所以这里适合小体积上报。
                data, (src_ip, src_port) = sock.recvfrom(8192)
                recv_ts = _now_ms()

                # ── 路径 1：CSI 二进制协议 ──
                csi = _try_parse_csi_binary(data)
                if csi is not None:
                    version, seq, t_ms, mac_str, rssi, csi_data = csi

                    # 主 JSONL 记录：csi_data 转 hex 存储
                    record: Dict[str, Any] = {
                        "recv_ts_ms": recv_ts,
                        "src_ip": src_ip,
                        "src_port": src_port,
                        "type": "csi_raw",
                        "ver": version,
                        "seq": seq,
                        "t_ms": t_ms,
                        "src_mac": mac_str,
                        "rssi": rssi,
                        "csi_len": len(csi_data),
                        "csi_hex": binascii.hexlify(csi_data).decode("ascii"),
                        "parse_ok": True,
                    }
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                    fp.flush()

                    # 可选的纯 hex 文件（一行一条，方便快速绘图/调试）
                    if args.csi_out is not None:
                        csi_fp.write(
                            "%d %d %d %s %d %s\n"
                            % (recv_ts, seq, t_ms, mac_str, rssi, record["csi_hex"])
                        )

                    if args.print:
                        # 打印时不输出 hex（太长），仅打摘要
                        summary = dict(record)
                        summary["csi_hex"] = "<%d bytes>" % len(csi_data)
                        sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                    continue  # 已处理，跳过 JSON 路径

                # ── 路径 2：文本 JSON（心跳 / csi_evt 等）──
                text = data.decode("utf-8", errors="replace").strip()
                event = _safe_json_loads(text)

                # 将接收时间、源地址和业务字段合并成一条记录。
                record = {
                    "recv_ts_ms": recv_ts,
                    "src_ip": src_ip,
                    "src_port": src_port,
                }

                if event is None:
                    record["raw"] = text
                    record["parse_ok"] = False
                else:
                    record.update(event)
                    record["parse_ok"] = True

                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                fp.flush()

                if args.print and event is not None:
                    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

    finally:
        if csi_fp is not None:
            csi_fp.close()


if __name__ == "__main__":
    raise SystemExit(main())
