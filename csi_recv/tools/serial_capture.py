#!/usr/bin/env python3
"""串口 CSI 数据采集脚本。

直接读 COM 口，写入 UTF-8 文本文件，不经过 idf.py monitor。
用法：python serial_capture.py COM23 data/still.txt
"""

import argparse
import os
import sys
import serial
import time


def main():
    parser = argparse.ArgumentParser(description="Serial CSI capture")
    parser.add_argument("port", help="COM port (e.g. COM23)")
    parser.add_argument("out", help="Output file path")
    parser.add_argument("--baud", type=int, default=921600, help="Baud rate")
    parser.add_argument("--warmup", type=int, default=10,
                        help="Warmup seconds after reset, all data discarded (default: 10)")
    args = parser.parse_args()

    # 先设 DTR/RTS=低，再打开，防止 CH343 拉高触发 ESP32 复位
    ser = serial.Serial()
    ser.port = args.port
    ser.baudrate = args.baud
    ser.timeout = 1
    ser.dtr = False
    ser.rts = False
    ser.open()
    ser.reset_input_buffer()
    sys.stderr.write(f"[serial_capture] {args.port} @ {args.baud} -> {args.out}\n")

    # 暖机等待（板子复位后需要时间重新启动+连 WiFi+发板重连）
    if args.warmup > 0:
        sys.stderr.write(f"[serial_capture] Warmup {args.warmup}s...\n")
        sys.stderr.flush()
        t0 = time.time()
        while time.time() - t0 < args.warmup:
            ser.readline()  # 丢弃
        sys.stderr.write(f"[serial_capture] Warmup done, capturing...\n")
    sys.stderr.write(f"[serial_capture] Ctrl+C to stop\n")
    sys.stderr.flush()
    sys.stderr.flush()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as fp:
        count = 0
        try:
            while True:
                line = ser.readline()
                if line:
                    text = line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
                    fp.write(text + "\n")
                    fp.flush()
                    count += 1
                    if count % 100 == 0:
                        sys.stderr.write(f"\r[serial_capture] {count} lines written...")
                        sys.stderr.flush()
        except KeyboardInterrupt:
            pass
        finally:
            ser.close()
            sys.stderr.write(f"\n[serial_capture] Done. {count} lines -> {args.out}\n")


if __name__ == "__main__":
    main()
