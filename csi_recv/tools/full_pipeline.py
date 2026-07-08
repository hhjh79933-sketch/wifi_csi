"""全管线可视化：still / motion / fall 三分类对比"""
import numpy as np
import matplotlib.pyplot as plt
import glob


def load_and_process(filepath, max_frames=999999):
    """加载 CSIRAW → I/Q → AGC幅度 + CFO/SFO相位差"""
    amps = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for l in f:
            if len(amps) >= max_frames: break
            if not l.startswith("CSIRAW"): continue
            p = l.split()
            try: r = bytes.fromhex(p[5])
            except: continue
            if len(r) != 128: continue
            amps.append(np.frombuffer(r, dtype=np.int8).astype(float))
    amps = np.array(amps)

    # I/Q
    I = amps[:, 0::2].astype(np.float32)
    Q = amps[:, 1::2].astype(np.float32)

    # 幅度 + AGC
    amp = np.sqrt(I**2 + Q**2)
    amp_agc = amp / (amp.mean(axis=1, keepdims=True) + 1e-8)

    # 相位 + CFO/SFO
    phase = np.arctan2(Q, I)
    dphase = np.diff(phase, axis=1)
    dphase = np.arctan2(np.sin(dphase), np.cos(dphase))
    dphase_abs = np.abs(dphase)

    return amp_agc, dphase_abs


# ── 加载 ──
print("Loading still...")
amp_s, dp_s = load_and_process("data/still.txt")
print("Loading motion...")
amp_m, dp_m = load_and_process("data/motion.txt")

# 合并所有 fall
fall_files = sorted(glob.glob("data/fall_*.txt"))
amp_f_list, dp_f_list = [], []
for fp in fall_files:
    print(f"Loading {fp}...")
    a, d = load_and_process(fp)
    amp_f_list.append(a); dp_f_list.append(d)
amp_f = np.concatenate(amp_f_list)
dp_f = np.concatenate(dp_f_list)

print(f"\nSTILL: {amp_s.shape[0]}  MOTION: {amp_m.shape[0]}  FALL: {amp_f.shape[0]}")

# ── 窗口化统计 ──
WIN, STEP = 48, 8

def window_stat(data, stat_fn):
    """滑窗统计"""
    stat = stat_fn(data, axis=1)  # 每帧一个值
    results = []
    for i in range(0, len(stat) - WIN, STEP):
        results.append(stat[i:i+WIN].mean())
    return np.array(results)


# ── 画图 ──
fig, axes = plt.subplots(3, 3, figsize=(18, 13))

# Row 1: AGC 幅度热力图
max_frames = 600
for ax, data, title in [
    (axes[0,0], amp_s, "STILL: AGC-fixed Amps"),
    (axes[0,1], amp_m, "MOTION: AGC-fixed Amps"),
    (axes[0,2], amp_f, "FALL (merged): AGC-fixed Amps"),
]:
    im = ax.imshow(data[:max_frames, :30].T, aspect="auto", origin="lower",
                   cmap="viridis", vmin=0.5, vmax=1.5)
    ax.set_title(title)
    plt.colorbar(im, ax=ax)

# Row 2: CFO/SFO-fixed |Δphase| 热力图
for ax, data, title in [
    (axes[1,0], dp_s, "STILL: |Adjacent Δphase|"),
    (axes[1,1], dp_m, "MOTION: |Adjacent Δphase|"),
    (axes[1,2], dp_f, "FALL (merged): |Adjacent Δphase|"),
]:
    im = ax.imshow(data[:max_frames, :30].T, aspect="auto", origin="lower",
                   cmap="inferno", vmin=0, vmax=0.3)
    ax.set_title(title)
    plt.colorbar(im, ax=ax)

# Row 3: 时域对比（AGC 幅度帧内方差）
for data, label, color, ax in [
    (amp_s, "STILL", "steelblue", axes[2,0]),
    (amp_m, "MOTION", "darkorange", axes[2,1]),
    (amp_f, "FALL", "crimson", axes[2,2]),
]:
    var_per_frame = np.var(data, axis=1)  # 子载波间方差
    ax.plot(range(len(var_per_frame)), var_per_frame, linewidth=0.3, color=color)
    ax.set_title(f"{label}: Subcarrier Variance")
    ax.set_xlabel("Frame"); ax.set_ylabel("Variance")

plt.tight_layout()
plt.savefig("data/full_pipeline.png", dpi=150)
print("\nSaved: data/full_pipeline.png")

# 定量
for name, data in [("STILL", amp_s), ("MOTION", amp_m), ("FALL", amp_f)]:
    var_f = np.var(data, axis=1)
    print(f"{name}: subcarrier_var={var_f.mean():.4f} ± {var_f.std():.4f}")

plt.show()
