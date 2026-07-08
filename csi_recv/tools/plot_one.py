#!/usr/bin/env python3
"""单文件 CSI 可视化：幅度时间曲线 + 子载波热力图 + 分布直方图

用法：
  python tools/plot_one.py data/still_new.txt
  python tools/plot_one.py data/still_new.txt --max-frames 2000
"""

import argparse, sys
import numpy as np
import matplotlib.pyplot as plt


def load_csi(filepath, max_frames=999999):
    amps = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if len(amps) >= max_frames:
                break
            if not line.startswith("CSIRAW"):
                continue
            parts = line.split()
            if len(parts) < 6:
                continue
            try:
                raw = bytes.fromhex(parts[5])
            except ValueError:
                continue
            if len(raw) != 128:
                continue
            amps.append(np.abs(np.frombuffer(raw, dtype=np.int8).astype(float)))

    amps = np.array(amps)
    print(f"Loaded {len(amps)} frames, shape={amps.shape}")
    return amps


def main():
    parser = argparse.ArgumentParser(description="Plot single CSI file")
    parser.add_argument("file", help="CSIRAW file path")
    parser.add_argument("--max-frames", type=int, default=999999)
    parser.add_argument("--out", default=None, help="Output PNG (default: auto-named)")
    args = parser.parse_args()

    amps = load_csi(args.file, args.max_frames)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fname = args.file.replace("\\", "/").split("/")[-1]

    # 左：均值幅度随时间
    means = amps.mean(axis=1)
    ax = axes[0]
    ax.plot(range(len(means)), means, linewidth=0.3, color="steelblue")
    ax.set_title(f"{fname}: Mean Amplitude")
    ax.set_xlabel("Frame")
    ax.set_ylabel("Mean Amplitude")
    ax.grid(True, alpha=0.2)

    # 中：子载波热力图
    ax = axes[1]
    im = ax.imshow(amps.T, aspect="auto", origin="lower",
                   extent=[0, amps.shape[0], 0, amps.shape[1]],
                   cmap="viridis")
    ax.set_title(f"{fname}: Subcarrier Heatmap")
    ax.set_xlabel("Frame"); ax.set_ylabel("Subcarrier")
    plt.colorbar(im, ax=ax, label="Amplitude")

    # 右：分布直方图
    ax = axes[2]
    ax.hist(means, bins=80, color="steelblue", alpha=0.7, edgecolor="white")
    ax.set_title(f"{fname}: Distribution")
    ax.set_xlabel("Mean Amplitude")
    ax.set_ylabel("Count")

    plt.tight_layout()
    out = args.out or f"data/{fname.replace('.txt', '.png')}"
    plt.savefig(out, dpi=120)
    print(f"Saved: {out}")
    plt.show()


if __name__ == "__main__":
    main()
