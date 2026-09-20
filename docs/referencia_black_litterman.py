import numpy as np
import csv
from scipy.optimize import minimize

# ============ 1. CARGAR SERIES ============
fechas, data = [], {"VOOG": [], "BNS": [], "VB": [], "IBIT": []}
with open("data/precios.csv") as f:
    for row in csv.DictReader(f):
        fechas.append(row["fecha"])
        for k in data:
            data[k].append(float(row[k]) if row[k] else np.nan)
P = {k: np.array(v) for k, v in data.items()}

def log_ret(p):
    return np.diff(np.log(p))

assets = ["VOOG", "BNS", "IBIT", "VB"]
R = {k: log_ret(P[k]) for k in assets}          # mensuales, con NaN para IBIT pre-2024

# --- Estimacion hibrida ---
# Vol y correlaciones VOOG/BNS/VB: muestra completa 5 anos (60 retornos)
# Vol de IBIT y sus correlaciones: muestra comun ene2024-sep2026 (32 retornos)
trad = ["VOOG", "BNS", "VB"]
n5 = len(R["VOOG"])
mask = ~np.isnan(R["IBIT"])

vols = {}
for k in trad:
    vols[k] = np.std(R[k], ddof=1) * np.sqrt(12)
vols["IBIT"] = np.std(R["IBIT"][mask], ddof=1) * np.sqrt(12)

corr = np.eye(4)
idx = {a: i for i, a in enumerate(assets)}
for i, a in enumerate(assets):
    for j, b in enumerate(assets):
        if i < j:
            if "IBIT" in (a, b):
                c = np.corrcoef(R[a][mask], R[b][mask])[0, 1]
            else:
                c = np.corrcoef(R[a], R[b])[0, 1]
            corr[i, j] = corr[j, i] = c

vol_vec = np.array([vols[a] for a in assets])
Sigma = np.outer(vol_vec, vol_vec) * corr

# Retornos historicos anualizados (informativo)
hist_ret = {k: (np.nanmean(R[k]) * 12) for k in assets}

print("=== PARAMETROS ESTIMADOS DE LOS DATOS (anualizados) ===")
for a in assets:
    print(f"  {a}: vol {vols[a]:.1%} | retorno hist. {hist_ret[a]:+.1%}")
print("\nCorrelaciones:")
print("        " + "  ".join(f"{a:>6}" for a in assets))
for i, a in enumerate(assets):
    print(f"  {a:<6}" + "  ".join(f"{corr[i,j]:6.2f}" for j in range(4)))

# ============ 2. BLACK-LITTERMAN ============
valor = 9739.94
w_actual = np.array([0.7944, 0.0892, 0.0676, 0.0488])
caps = np.array([28.0, 0.116, 1.9, 2.5])   # large growth, BNS, BTC, small caps (US$ trillones)
w_mkt = caps / caps.sum()
delta, tau, rf = 2.5, 0.05, 0.04

pi = delta * Sigma @ w_mkt

# Views del usuario (identicos a la ronda anterior)
Pv = np.array([
    [0, 0, 1, 0],     # IBIT neutral
    [1, 0, 0, -1],    # VOOG > VB
    [0, 1, 0, 0],     # BNS positivo
])
Q = np.array([0.03 - rf, 0.03, 0.10 - rf])
Omega = np.diag(np.diag(Pv @ (tau * Sigma) @ Pv.T))

inv_tS = np.linalg.inv(tau * Sigma)
inv_O = np.linalg.inv(Omega)
M = np.linalg.inv(inv_tS + Pv.T @ inv_O @ Pv)
mu_bl = M @ (inv_tS @ pi + Pv.T @ inv_O @ Q)
Sigma_bl = Sigma + M

print("\n=== RETORNOS: equilibrio -> posterior BL (en exceso de rf) ===")
for i, a in enumerate(assets):
    print(f"  {a}: {pi[i]:+.2%} -> {mu_bl[i]:+.2%}")

# ============ 3. OPTIMIZACION (2%-70% por activo) ============
def neg_u(w):
    return -(w @ mu_bl - 0.5 * delta * w @ Sigma_bl @ w)

cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
res = minimize(neg_u, np.array([0.6, 0.2, 0.05, 0.15]),
               bounds=[(0.02, 0.70)] * 4, constraints=cons)
w_opt = res.x

def stats(w):
    ret = w @ (mu_bl + rf)
    vol = np.sqrt(w @ Sigma @ w)
    return ret, vol, (ret - rf) / vol

print("\n=== PESOS OPTIMOS (datos reales) ===")
for i, a in enumerate(assets):
    print(f"  {a:<5} actual {w_actual[i]:>6.1%} -> {w_opt[i]:>6.1%} | "
          f"{w_opt[i]*valor:>8,.0f} USD | cambio {(w_opt[i]-w_actual[i])*valor:>+8,.0f}")

for nombre, w in [("Actual", w_actual), ("Optimo", w_opt)]:
    r, v, s = stats(w)
    print(f"  {nombre:<7}: ret {r:.2%} | vol {v:.2%} | Sharpe {s:.2f}")
