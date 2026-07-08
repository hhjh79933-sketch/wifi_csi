"""阈值检测 v3：全子载波 + 前置静默 + 尖峰密度 + 后置静默"""
import numpy as np

WIN, STEP = 48, 8
THRESHOLD = 1.08
SILENCE_SEC = 2.5
SILENCE_WIN = int(SILENCE_SEC * 1000 / (STEP * 1000 / 92))  # ~29 窗
MAX_SPIKE_DENSE = 8    # 超过此数 → 运动

def process_file(fp):
    amps = np.array([np.frombuffer(bytes.fromhex(l.split()[5]), dtype=np.int8).astype(float)
        for l in open(fp, encoding='utf-8', errors='replace')
        if l.startswith("CSIRAW") and len(bytes.fromhex(l.split()[5]))==128])
    I = amps[:,0::2].astype(np.float32)
    Q = amps[:,1::2].astype(np.float32)
    raw = np.sqrt(I**2+Q**2)
    agc = raw / (raw.mean(1, keepdims=True)+1e-8)
    var = np.var(agc, axis=1)

    wins = np.array([var[i:i+WIN].mean() for i in range(0, len(var)-WIN, STEP)])
    base = wins[:10].mean()
    th = base * THRESHOLD

    events = []
    pre_silence = 0
    in_spike = False
    spike_count = 0
    post_silence = 0
    spike_pre = 0

    for i in range(len(wins)):
        if wins[i] > th:
            if not in_spike:
                spike_pre = pre_silence
                in_spike = True
                spike_count = 1
                post_silence = 0
                events.append((i*STEP,
                    f"SPIKE({wins[i]/base:.2f}x, pre={pre_silence})", wins[i]/base))
            else:
                spike_count += 1
            pre_silence = 0
        else:
            pre_silence += 1
            if in_spike:
                post_silence += 1
                if spike_count > MAX_SPIKE_DENSE:
                    events.append((i*STEP,
                        f"MOTION_DENSE(sc={spike_count})", 0))
                    in_spike = False
                elif post_silence >= SILENCE_WIN:
                    if spike_pre >= SILENCE_WIN:
                        events.append((i*STEP, ">>> FALL CONFIRMED <<<", 1))
                    else:
                        events.append((i*STEP,
                            f"MOTION_STOP(pre={spike_pre})", 0))
                    in_spike = False

    # 文件末尾结算
    if in_spike:
        if spike_count > MAX_SPIKE_DENSE:
            events.append((len(wins)*STEP, f"END_DENSE(sc={spike_count})", 0))
        elif spike_pre >= SILENCE_WIN and post_silence >= SILENCE_WIN:
            events.append((len(wins)*STEP, ">>> FALL CONFIRMED(END) <<<", 1))
        else:
            events.append((len(wins)*STEP,
                f"END?(pre={spike_pre},sc={spike_count},post={post_silence})", 0))

    return base, th, wins, events

for fp in ["test/test_1.txt", "test/test_2.txt", "test/test_3.txt", "test/test_4.txt"]:
    base, th, wins, events = process_file(fp)
    print(f"\n{fp}:")
    print(f"  base={base:.4f} th={th:.4f}")
    print(f"  max/base={wins.max()/base:.2f}x")
    collapsed = []
    for f, e, v in events:
        if "FALL" in str(e) or "DENSE" in str(e) or "STOP" in str(e) or "END" in str(e):
            collapsed.append((f, e, round(v,2)))
        elif "SPIKE" in str(e):
            collapsed.append((f, e.split(",")[0]+")", round(v,2)))
    print(f"  events: {collapsed}")
    if any("CONFIRMED" in str(e) for _,e,_ in events):
        print(f"  >>> FALL DETECTED <<<")
