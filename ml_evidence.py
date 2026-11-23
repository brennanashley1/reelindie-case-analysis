"""
ReelIndie - machine learning evidence charts
Run from the folder that holds data/ :   python ml_evidence.py
Makes 4 charts in ml_charts/ that show how the k-means segmentation was built and tested.
"""
import os
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, adjusted_rand_score

DATA = "data/"
OUT = "ml_charts/"
os.makedirs(OUT, exist_ok=True)

# ---------- same data prep as the main script ----------
r = pd.read_csv(DATA + "rental.csv")
p = pd.read_csv(DATA + "payment.csv")
f = pd.read_csv(DATA + "film.csv")
r["rental_date"] = pd.to_datetime(r.rental_date, format="mixed")
df = r.merge(p[["rental_id", "amount"]], on="rental_id").merge(f[["film_id", "rental_rate"]], on="film_id")
df = df[df.rental_date < "2025-01-01"].copy()
df["ext_fee"] = (df.amount - df.rental_rate).clip(lower=0)
df["extended"] = df.ext_fee > 0

FEATURES = ["rentals", "avg_price", "pct_extended"]

def customer_features(d):
    return d.groupby("customer_id").agg(rentals=("rental_id", "count"),
                                        avg_price=("rental_rate", "mean"),
                                        pct_extended=("extended", "mean"),
                                        spend=("amount", "sum"))

def kmeans(X, k):
    return KMeans(n_clusters=k, n_init=50, random_state=42).fit(X)

cust = customer_features(df)
X = StandardScaler().fit_transform(cust[FEATURES])

# ---------- chart style (matches the deck) ----------
NAVY, BLUE, ORANGE, INK, MUTED = "#15172A", "#2A78D6", "#EB6834", "#1F2330", "#6B6E7A"
plt.rcParams.update({"font.family": ["Calibri", "Carlito", "DejaVu Sans"], "font.size": 15,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.edgecolor": "#C9CCD3", "text.color": INK, "axes.labelcolor": MUTED,
                     "xtick.color": INK, "ytick.color": INK})
SIZE = (10, 6.25)

def save(name):
    plt.tight_layout()
    plt.savefig(OUT + name + ".png", dpi=200, facecolor="white")
    plt.close()
    print("saved", name)

# ---------- 1. Choosing k: elbow + silhouette ----------
ks = range(2, 9)
inertia, sil = [], []
for k in ks:
    m = kmeans(X, k)
    inertia.append(m.inertia_)
    sil.append(silhouette_score(X, m.labels_))
print("k, inertia, silhouette:", [(k, round(i), round(s, 3)) for k, i, s in zip(ks, inertia, sil)])

fig, ax1 = plt.subplots(figsize=SIZE)
ax1.plot(list(ks), inertia, marker="o", color=BLUE, linewidth=3, markersize=9, label="Within-cluster error (elbow)")
ax1.set_xlabel("Number of clusters (k)", fontsize=15)
ax1.set_ylabel("Within-cluster error", color=BLUE, fontsize=15)
ax2 = ax1.twinx()
ax2.spines["right"].set_visible(True)
ax2.plot(list(ks), sil, marker="s", color=MUTED, linewidth=2, linestyle="--", markersize=8, label="Silhouette score")
ax2.set_ylabel("Silhouette score (higher = better separated)", color=MUTED, fontsize=14)
ax1.axvline(4, color=ORANGE, linewidth=2, zorder=0)
ax1.text(4.9, max(inertia) - 120, "k = 4 chosen:\nhighest silhouette score", color=ORANGE, fontsize=16, fontweight="bold", va="center")
h1, l1 = ax1.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, frameon=False, loc="upper right", fontsize=13)
save("ml1_choosing_k")

# ---------- 2. What each cluster looks like ----------
model = kmeans(X, 4)
cust["segment"] = model.labels_
prof = cust.groupby("segment").agg(customers=("rentals", "size"), rentals=("rentals", "mean"),
                                   avg_price=("avg_price", "mean"), pct_extended=("pct_extended", "mean"),
                                   revenue=("spend", "sum"))
prof["share"] = prof.revenue / prof.revenue.sum()
names = {prof.rentals.idxmax(): "Superfans", prof.avg_price.idxmin(): "Bargain hunters",
         prof.pct_extended.idxmax(): "Binge-keepers"}
for s in prof.index:
    names.setdefault(s, "On-time watchers")
prof.index = [names[s] for s in prof.index]
prof = prof.loc[["Superfans", "Bargain hunters", "Binge-keepers", "On-time watchers"]]
print(prof.round(2))

z = (prof[FEATURES] - cust[FEATURES].mean()) / cust[FEATURES].std()   # how far each cluster sits from average
fig, ax = plt.subplots(figsize=SIZE)
im = ax.imshow(z.values, cmap="RdBu_r", vmin=-1.6, vmax=1.6, aspect="auto")
ax.set_xticks(range(3)); ax.set_xticklabels(["Rentals per\ncustomer", "Average price\nchosen", "Share of rentals\nextended"], fontsize=15)
ax.set_yticks(range(4)); ax.set_yticklabels([f"{n}\n({int(c)} customers)" for n, c in zip(prof.index, prof.customers)], fontsize=15)
fmt = [lambda v: f"{v:.1f}", lambda v: f"${v:.2f}", lambda v: f"{v:.0%}"]
for i in range(4):
    for j, col in enumerate(FEATURES):
        val = prof[col].iloc[i]
        ax.text(j, i, fmt[j](val), ha="center", va="center", fontsize=20, fontweight="bold",
                color="white" if abs(z.values[i, j]) > 0.9 else INK)
for s in ax.spines.values():
    s.set_visible(False)
ax.tick_params(length=0)
cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
cb.set_label("Below average  ←  →  Above average", color=MUTED, fontsize=13)
cb.set_ticks([])
save("ml2_cluster_profiles")

# ---------- 3. Stability test: cluster early weeks and late weeks separately ----------
early = df[df.rental_date < "2024-11-15"]
late = df[df.rental_date >= "2024-11-15"]
ce, cl = customer_features(early), customer_features(late)
both = ce.index.intersection(cl.index)
lab_e = kmeans(StandardScaler().fit_transform(ce.loc[both, FEATURES]), 4).labels_
lab_l = kmeans(StandardScaler().fit_transform(cl.loc[both, FEATURES]), 4).labels_
ari = adjusted_rand_score(lab_e, lab_l)
same_seed = adjusted_rand_score(kmeans(X, 4).labels_, model.labels_)
print(f"Adjusted Rand Index early vs late: {ari:.3f}  (1.0 = same groups; re-run on same data: {same_seed:.2f})")

# share of each early cluster's customers who land in their most likely late cluster
ct = pd.crosstab(lab_e, lab_l, normalize="index")
stay = ct.max(axis=1).mean()
print(f"Average share that stay together: {stay:.0%} (random would be ~25%)")

fig, ax = plt.subplots(figsize=SIZE)
bars = ax.bar(["Same data,\nrun twice", "Early weeks vs\nlate weeks"], [same_seed, ari], color=[BLUE, ORANGE], width=0.5)
ax.text(0, same_seed + 0.03, f"{same_seed:.2f}", ha="center", va="bottom", fontsize=26, fontweight="bold")
ax.text(1, 0.03, f"{abs(ari):.2f}", ha="center", va="bottom", fontsize=26, fontweight="bold", color=ORANGE)
ax.text(1, 0.2, "No agreement:\ncustomers reshuffle\ninto new groups", ha="center", va="bottom", fontsize=16, color=INK)
ax.axhline(0, color="#C9CCD3", linewidth=1)
ax.set_ylim(0, 1.15)
ax.set_yticks([0, 0.5, 1]); ax.set_yticklabels(["0\nrandom", "0.5", "1.0\nidentical"], fontsize=13)
ax.set_ylabel("Adjusted Rand Index (cluster agreement)", fontsize=14)
ax.tick_params(axis="x", labelsize=16)
save("ml3_stability_test")

# ---------- 4. Revenue share: top early spenders fade back to average ----------
se = early.groupby("customer_id").amount.sum()
sl = late.groupby("customer_id").amount.sum()
top = se.nlargest(169).index
shares = [se[top].sum() / se.sum(), sl.reindex(top, fill_value=0).sum() / sl.sum()]
fig, ax = plt.subplots(figsize=SIZE)
bars = ax.bar(["Early weeks\nSep 21 – Nov 9", "Late weeks\nNov 23 – Dec 21"], shares, color=[ORANGE, BLUE], width=0.5)
ax.bar_label(bars, labels=[f"{v:.0%}" for v in shares], padding=6, fontsize=26, fontweight="bold")
ax.axhline(169 / 599, color=MUTED, linestyle="--", linewidth=1.6, zorder=0)
ax.text(1.3, 169 / 599 + 0.01, f"Their share of\ncustomers: {169/599:.0%}", color=MUTED, fontsize=14, va="bottom")
ax.set_xlim(-0.45, 2.05); ax.set_yticks([]); ax.spines["left"].set_visible(False)
ax.set_xlabel("Revenue share of the 169 biggest early spenders", fontsize=14, labelpad=8)
ax.tick_params(axis="x", labelsize=15, length=0)
save("ml4_top_spenders_fade")
