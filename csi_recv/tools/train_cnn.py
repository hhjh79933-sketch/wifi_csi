"""CNN v2: AGC 方差时序曲线 → 分类（与手工状态机同特征，自动学决策边界）"""
import numpy as np
import glob, os, torch, torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import classification_report, confusion_matrix

WIN_FRAMES = 128; STRIDE = 64; BATCH = 16; EPOCHS = 80; LR = 1e-3
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

def load_variance(filepath):
    """返回 (n_frames,) 每帧 AGC 子载波方差"""
    amps = np.array([np.frombuffer(bytes.fromhex(l.split()[5]), dtype=np.int8).astype(float)
        for l in open(filepath, encoding='utf-8', errors='replace')
        if l.startswith("CSIRAW") and len(bytes.fromhex(l.split()[5]))==128])
    if len(amps) < WIN_FRAMES: return None
    I = amps[:,0::2].astype(np.float32); Q = amps[:,1::2].astype(np.float32)
    raw = np.sqrt(I**2+Q**2)
    agc = raw / (raw.mean(1, keepdims=True)+1e-8)
    return np.var(agc, axis=1)  # (n_frames,)

print("Loading...")
X_all, y_all = [], []

# 静止
v = load_variance("data/still.txt")
for s in range(0, len(v)-WIN_FRAMES, STRIDE):
    X_all.append(v[s:s+WIN_FRAMES]); y_all.append(0)
print(f"  still: {len([yy for yy in y_all if yy==0])} windows")

# 运动
v = load_variance("data/motion.txt")
for s in range(0, len(v)-WIN_FRAMES, STRIDE):
    X_all.append(v[s:s+WIN_FRAMES]); y_all.append(1)
print(f"  motion: {sum(1 for yy in y_all if yy==1)} windows")

# 跌倒：冲击区 ± 0.5s 标 FALL，其余标 STILL
n_fall_before = len(y_all)
for fp in sorted(glob.glob("data/fall_*.txt")):
    v = load_variance(fp); n = len(v)
    # 找方差最大帧 = 冲击中心
    peak = np.argmax(v)
    for s in range(0, n-WIN_FRAMES, STRIDE):
        mid = s + WIN_FRAMES//2
        # 窗口中心离冲击中心 32 帧内 → FALL
        label = 2 if abs(mid - peak) < 32 else 0
        X_all.append(v[s:s+WIN_FRAMES]); y_all.append(label)
n_fall = sum(1 for yy in y_all[n_fall_before:] if yy==2)
print(f"  fall x10: {len(y_all)-n_fall_before} windows (fall={n_fall})")

X = np.array(X_all, dtype=np.float32)[:, :, None]  # (N, 128, 1)
y = np.array(y_all, dtype=np.int64)
print(f"Total: {len(X)}  STILL={sum(y==0)} MOTION={sum(y==1)} FALL={sum(y==2)}")

# ═══════════════ 模型 (1D-CNN on variance) ═══════════════
class FallCNN(nn.Module):
    def __init__(self, n_classes=3):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(1, 16, 7, padding=3), nn.BatchNorm1d(16), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(16, 32, 7, padding=3), nn.BatchNorm1d(32), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(32, 64, 7, padding=3), nn.BatchNorm1d(64), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 128, 5, padding=2), nn.BatchNorm1d(128), nn.ReLU(),
            nn.AdaptiveAvgPool1d(4),
        )
        self.head = nn.Sequential(
            nn.Flatten(), nn.Dropout(0.3),
            nn.Linear(512, 64), nn.ReLU(),
            nn.Linear(64, n_classes)
        )
    def forward(self, x):
        return self.head(self.conv(x.permute(0,2,1)))

# ═══════════════ 训练 ═══════════════
skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
all_preds = np.zeros(len(y))
all_probs = np.zeros((len(y), 3))

for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
    print(f"\n{'='*40}\nFold {fold+1}/3")
    X_tr, X_vl = torch.FloatTensor(X[train_idx]), torch.FloatTensor(X[val_idx])
    y_tr, y_vl = torch.LongTensor(y[train_idx]), torch.LongTensor(y[val_idx])
    loader = DataLoader(TensorDataset(X_tr, y_tr), BATCH, shuffle=True)

    model = FallCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(EPOCHS):
        model.train()
        for bx, by in loader:
            bx, by = bx.to(device), by.to(device)
            opt.zero_grad()
            loss = loss_fn(model(bx), by)
            loss.backward()
            opt.step()
        if (epoch+1) % 10 == 0:
            model.eval()
            with torch.no_grad():
                acc = (model(X_vl.to(device)).argmax(1) == y_vl.to(device)).float().mean()
            print(f"  Epoch {epoch+1:2d}: loss={loss.item():.4f}  val_acc={acc:.3f}")

    model.eval()
    with torch.no_grad():
        logits = model(X_vl.to(device)).cpu()
        all_preds[val_idx] = logits.argmax(1).numpy()
        all_probs[val_idx] = torch.softmax(logits, 1).numpy()

# ═══════════════ 评估 ═══════════════
print(f"\n{'='*40}\n=== 3-Fold CV Results ===")
print(classification_report(y, all_preds, target_names=["STILL","MOTION","FALL"]))

cm = confusion_matrix(y, all_preds)
print("Confusion Matrix:")
print(f"         STILL MOTION FALL")
for i, name in enumerate(["STILL","MOTION","FALL"]):
    print(f"  {name:6s} {cm[i,0]:5d} {cm[i,1]:6d} {cm[i,2]:5d}")

# 保存模型
torch.save(model.state_dict(), "models/fall_cnn_v2.pth")
print("\nModel saved: models/fall_cnn_v2.pth")
