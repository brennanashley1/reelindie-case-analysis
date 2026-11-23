import pandas as pd

rental = pd.read_csv("data/rental.csv")
payment = pd.read_csv("data/payment.csv")
film = pd.read_csv("data/film.csv")
film_category = pd.read_csv("data/film_category.csv")
category = pd.read_csv("data/category.csv")
customer = pd.read_csv("data/customer.csv")

# Dates come in as text; turn them into real dates
rental["rental_date"] = pd.to_datetime(rental["rental_date"])
rental["return_date"] = pd.to_datetime(rental["return_date"])

# Give each film its genre name
film = film.merge(film_category[["film_id", "category_id"]], on="film_id")
film = film.merge(category.rename(columns={"name":"category"}), on="category_id")

# One big table: every rental + its payment + its film 
df = rental.merge(payment[["rental_id", "amount"]], on="rental_id").merge(film, on="film_id")

# Drop the odd June 2025 batch (182 rentals with one timestamp)
df = df[df.rental_date < "2025-01-01"]

# Extension fee = what they paid above the listed price
df["ext_fee"] = (df.amount - df.rental_rate).clip(lower=0).round(2)
df["extended"] = df.ext_fee > 0

print(len(df), "rentals")
print(df[["title", "rental_rate", "amount", "ext_fee"]].head())

print("=== STEP 1")
# Each customer's first rental ->which month they joined
first = df.groupby("customer_id").rental_date.min()
print(first.dt.to_period("M").value_counts().sort_index())

# Label the five snapshot weeks (November has two, so split it)
df["week"] = df.rental_date.dt.to_period("M").astype(str)
df.loc[(df.rental_date >= "2024-11-20") & (df.rental_date < "2024-12-01"), "week"] = "2024-11b"

weekly = df.groupby("week").agg(rentals=("rental_id", "count"),
                                revenue=("amount", "sum"),
                                customers=("customer_id", "nunique"))
weekly["rentals_per_customer"] = weekly.rentals / weekly.customers
print(weekly.round(1))

print("=== STEP 2")
total = df.amount.sum()
ext = df.ext_fee.sum()
print(f"Revenue ${total:,.0f} | extension fees ${ext:,.0f} = {ext/total:.0%} | {df.extended.mean():.0%} of rentals extended")

# Share of rentals extended, by rental window (3-7 days)
print(df.groupby("rental_duration").extended.mean().round(2))

# What would a "+3 days" option at checkout do to today's fees?
# Extended up to 3 days -> pays the option (or less, if the fee was cheaper); longer -> option + $1/day after that
fees = df.loc[df.extended, "ext_fee"]
for price in [1.99, 2.99]:
    with_option = fees.where(fees > 3, fees.clip(upper=price)).where(fees <= 3, price + (fees - 3))
    change = with_option.sum() - fees.sum()
    print(f"+3 days at ${price}: ReelIndie collects ${abs(change):,.0f} {'less' if change < 0 else 'more'} in fees")

print("=== STEP 3")
tiers = df.groupby("rental_rate").agg(titles=("film_id", "nunique"),
                                      rentals=("rental_id", "count"),
                                      revenue=("amount", "sum"))
tiers["rentals_per_title"] = tiers.rentals / tiers.titles
tiers["revenue_per_title"] = tiers.revenue / tiers.titles
print(tiers.round(1))

# What if the $0.99 films cost $2.99?
n = tiers.loc[0.99, "rentals"]
fee99 = df.loc[df.rental_rate == 0.99, "ext_fee"].sum()     # renters who leave also stop paying extension fees

def gain(leave):
    return n * (1 - leave) * 2.99 + fee99 * (1 - leave) - (n * 0.99 + fee99)

breakeven = (n * 2.99 + fee99 - n * 0.99 - fee99) / (n * 2.99 + fee99)
print(f"No drop: +${gain(0):,.0f} | 40% leave: +${gain(0.4):,.0f} | break-even if {breakeven:.0%} leave")

print("=== STEP 4")
titles = film.groupby("category").film_id.count()
genre = df.groupby("category").amount.sum().to_frame("revenue")
genre["titles"] = titles
genre["filmmaker_per_title"] = genre.revenue * 0.75 / genre.titles
print(genre.sort_values("filmmaker_per_title", ascending=False).round(0))

# How much of a title's earnings does genre explain?
import statsmodels.formula.api as smf
per_title = df.groupby(["film_id", "category"]).amount.sum().mul(0.75).rename("earn").reset_index()
genre_model = smf.ols("earn ~ C(category)", data=per_title).fit()
print(f"Genre explains {genre_model.rsquared:.1%} of filmmaker earnings per title (p = {genre_model.f_pvalue:.2f})")

print("=== STEP 5")
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans

# One row per customer, like Access query 12
cust = df.groupby("customer_id").agg(rentals=("rental_id", "count"),
                                     spend=("amount", "sum"),
                                     avg_price=("rental_rate", "mean"),
                                     pct_extended=("extended", "mean"))

# Put the three features on the same scale, then cluster
X = StandardScaler().fit_transform(cust[["rentals", "avg_price", "pct_extended"]])
cust["segment"] = KMeans(n_clusters=4, n_init=50, random_state=42).fit_predict(X)

summary = cust.groupby("segment").agg(customers=("rentals", "size"),
                                      rentals=("rentals", "mean"),
                                      avg_price=("avg_price", "mean"),
                                      pct_extended=("pct_extended", "mean"),
                                      revenue=("spend", "sum"))
summary["share"] = summary.revenue / summary.revenue.sum()
print(summary.round(2))

# Do the groups last? Split into early weeks (Sep 21 - Nov 9) and late weeks (Nov 23 - Dec 21)
early = df[df.rental_date < "2024-11-15"]
late = df[df.rental_date >= "2024-11-15"]
spend_early = early.groupby("customer_id").amount.sum()
spend_late = late.groupby("customer_id").amount.sum()
top = spend_early.nlargest(169).index                          # the 169 biggest early spenders
share_early = spend_early[top].sum() / spend_early.sum()
share_late = spend_late.reindex(top, fill_value=0).sum() / spend_late.sum()
print(f"Top 169 early spenders: {share_early:.0%} of early revenue -> {share_late:.0%} of late revenue "
      f"(they are {169/599:.0%} of customers)")

def habit(d, col):
    return d.groupby("customer_id")[col].mean()
early = early.assign(cheap=early.rental_rate == 0.99)
late = late.assign(cheap=late.rental_rate == 0.99)
print(f"Habit repeats? $0.99 picks r = {habit(early, 'cheap').corr(habit(late, 'cheap')):.2f} | "
      f"extending r = {habit(early, 'extended').corr(habit(late, 'extended')):.2f}")

print("=== STEP 6")
import statsmodels.formula.api as smf

# Rentals per film (films never rented count as 0)
per_film = df.groupby("film_id").rental_id.count().rename("rentals")
f = film.set_index("film_id").join(per_film).fillna({"rentals": 0})

# Turn special features into 0/1 columns
for feat in ["Trailers", "Commentaries", "Deleted Scenes", "Behind the Scenes"]:
    f[feat.replace(" ", "_")] = f.special_features.str.contains(feat).astype(int)

model = smf.ols("rentals ~ length + rental_rate + rental_duration + C(rating) + C(category)"
                " + Trailers + Commentaries + Deleted_Scenes + Behind_the_Scenes + C(release_year)",
                data=f).fit()
print(f"R-squared: {model.rsquared:.3f}")
print(model.pvalues[model.pvalues < 0.10].round(3))

print("=== STEP 7")
import wbgapi as wb

address = pd.read_csv("data/address.csv")
city = pd.read_csv("data/city.csv")
country = pd.read_csv("data/country.csv")

# Customers per country (like Access query 15)
geo = customer.merge(address, on="address_id").merge(city, on="city_id").merge(country, on="country_id")
ctry = geo.groupby("country").customer_id.count().rename("customers").to_frame()

# World Bank: internet use % and population, latest year per country
wbd = wb.data.DataFrame(["IT.NET.USER.ZS", "SP.POP.TOTL"], mrnev=1, labels=True)
wbd = wbd.reset_index().rename(columns={"Country": "country",
                                        "IT.NET.USER.ZS": "internet_pct",
                                        "SP.POP.TOTL": "population"})

# Match World Bank names to ReelIndie names
rename = {"Czechia": "Czech Republic", "Slovak Republic": "Slovakia",
          "Iran, Islamic Rep.": "Iran", "Egypt, Arab Rep.": "Egypt",
          "Viet Nam": "Vietnam", "Turkiye": "Turkey", "Korea, Rep.": "South Korea",
          "Venezuela, RB": "Venezuela", "Yemen, Rep.": "Yemen"}
# A few small places (Puerto Rico, Hong Kong, Taiwan...) don't match and are left out (30 of 599 customers, about 5%)
wbd["country"] = wbd.country.replace(rename)
ctry = ctry.join(wbd.set_index("country")[["internet_pct", "population"]], how="left")
print("No match:", ctry[ctry.internet_pct.isna()].index.tolist())

# Key metric: customers per million internet users
ctry["internet_users_m"] = ctry.population * ctry.internet_pct / 100 / 1_000_000
ctry = ctry[ctry.internet_users_m > 0]
ctry["per_m_users"] = ctry.customers / ctry.internet_users_m

# Finding 1: Spanish-speaking vs everyone else
spanish = {"Mexico", "Argentina", "Colombia", "Spain", "Venezuela", "Peru", "Chile",
           "Ecuador", "Bolivia", "Paraguay", "Dominican Republic", "Puerto Rico"}
ctry["spanish"] = ctry.index.isin(spanish)
g = ctry.groupby("spanish")[["customers", "internet_users_m"]].sum()
g["per_m"] = g.customers / g.internet_users_m
print(g.round(3))
print("Ratio:", round(g.per_m[True] / g.per_m[False], 1))

# Finding 2: gap if the 15 biggest markets matched the US rate
big = ctry.sort_values("internet_users_m", ascending=False).head(15).copy()
us_rate = ctry.loc["United States", "per_m_users"]
big["gap"] = (big.internet_users_m * us_rate - big.customers).clip(lower=0)
avg_spend = df.amount.sum() / df.customer_id.nunique()
print(f"US rate {us_rate:.3f} | gap {big.gap.sum():.0f} customers | about ${big.gap.sum() * avg_spend:,.0f}")

print("=== STEP 8")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from pathlib import Path

# One style for every chart, so the slides match
BLUE, ORANGE, INK, MUTED = "#2A78D6", "#EB6834", "#1F2330", "#6B6E7A"
plt.rcParams.update({"font.family": ["Century Gothic", "DejaVu Sans"], "font.size": 17,
    "text.color": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.edgecolor": "#C9CCD3"})
SIZE = (10, 6.25)          # every chart the same shape, so they line up on the slides
Path("deck_charts").mkdir(exist_ok=True)

def save(name):
    plt.tight_layout()
    plt.savefig(f"deck_charts/{name}.png", dpi=200)
    plt.close()
    print("saved", name)

def clean_bars(ax, top):
    """Values sit on the bars, so hide the y-axis and leave headroom."""
    ax.set_ylim(0, top * 1.15)
    ax.set_yticks([])
    ax.tick_params(axis="x", length=0)

def note(ax, text):
    ax.set_xlabel(text, color=MUTED, fontsize=15, labelpad=10)

# Slide 2: weekly revenue, renters inside each bar, NEW customers under each week
first_week = df.sort_values("rental_date").groupby("customer_id").week.first()   # week each customer first rented
new_per_week = first_week.value_counts().reindex(weekly.index, fill_value=0)
fig, ax = plt.subplots(figsize=SIZE)
bars = ax.bar(["Sep 21", "Oct 12", "Nov 2", "Nov 23", "Dec 14"], weekly.revenue, color=BLUE, width=0.62)
ax.bar_label(bars, labels=[f"${v:,.0f}" for v in weekly.revenue], padding=6, fontsize=19, fontweight="bold")
ax.bar_label(bars, labels=[f"{c}\nrenters" for c in weekly.customers], label_type="center",
             color="white", fontsize=15, fontweight="bold")
clean_bars(ax, weekly.revenue.max())
ax.tick_params(axis="x", pad=6)
for i, n in enumerate(new_per_week):            # orange when acquisition has stalled (0 or 1)
    ax.text(i, -0.12, f"+{n} new", transform=ax.get_xaxis_transform(), ha="center", va="top",
            fontsize=17, fontweight="bold", color=ORANGE if n <= 1 else MUTED)
ax.set_xlabel("Weekly revenue (top) · renters that week (inside) · new customers (bottom)",
              color=MUTED, fontsize=15, labelpad=52)
save("c2_revenue")

# Slide 3: customer segments (from Step 5), Superfans in orange
p = cust.groupby("segment").agg(r=("rentals", "mean"), price=("avg_price", "mean"), e=("pct_extended", "mean"))
names = {p.r.idxmax(): "Superfans", p.price.idxmin(): "Bargain hunters", p.e.idxmax(): "Binge-keepers"}
names.update({k: "On-time watchers" for k in p.index if k not in names})
colors = {"Superfans": ORANGE, "Bargain hunters": BLUE, "Binge-keepers": "#1BAF7A", "On-time watchers": "#6250D6"}
fig, ax = plt.subplots(figsize=SIZE)
for seg, nm in sorted(names.items(), key=lambda kv: kv[1] == "Superfans"):   # Superfans drawn last, on top
    grp = cust[cust.segment == seg]
    ax.scatter(grp.rentals, grp.spend, s=46, color=colors[nm], alpha=0.85, edgecolor="white", linewidth=0.6,
               label=f"{nm} ({len(grp)})")
ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
ax.spines["left"].set_visible(True)
ax.tick_params(length=0, labelsize=15)
ax.grid(color="#ECEEF2", linewidth=1)
ax.set_axisbelow(True)
ax.set_ylabel("Total spend", color=MUTED, fontsize=15)
note(ax, "Rentals per customer (5 snapshot weeks)")
ax.legend(loc="upper left", frameon=False, fontsize=15, markerscale=1.6, handletextpad=0.3)
save("c3_segments")

HALF = (6.4, 4.0)          # two charts side by side on slide 3

# Slide 3 (left): the four k-means segments, half size
fig, ax = plt.subplots(figsize=HALF)
for seg, nm in sorted(names.items(), key=lambda kv: kv[1] == "Superfans"):
    grp = cust[cust.segment == seg]
    ax.scatter(grp.rentals, grp.spend, s=26, color=colors[nm], alpha=0.85, edgecolor="white", linewidth=0.4,
               label=f"{nm} ({len(grp)})")
ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
ax.spines["left"].set_visible(True)
ax.tick_params(length=0, labelsize=13)
ax.grid(color="#ECEEF2", linewidth=1)
ax.set_axisbelow(True)
ax.set_ylabel("Total spend", color=MUTED, fontsize=13)
ax.set_xlabel("Rentals per customer", color=MUTED, fontsize=13)
ax.legend(loc="upper left", frameon=False, fontsize=12.5, markerscale=1.5, handletextpad=0.2, labelspacing=0.3)
save("c3_segments_half")

# Slide 3: the top early spenders fade back to their normal share (from Step 5)
fig, ax = plt.subplots(figsize=HALF)
bars = ax.bar(["Early weeks\nSep 21 – Nov 9", "Late weeks\nNov 23 – Dec 21"], [share_early, share_late],
              color=[ORANGE, BLUE], width=0.5)
ax.bar_label(bars, labels=[f"{v:.0%}" for v in [share_early, share_late]], padding=6, fontsize=22, fontweight="bold")
ax.axhline(169 / 599, color=MUTED, linestyle="--", linewidth=1.6, zorder=0)
ax.text(1.3, 169 / 599 + 0.01, f"Their share of\ncustomers: {169/599:.0%}", va="bottom", ha="left", color=MUTED, fontsize=13)
ax.set_xlim(-0.45, 2.05)
ax.tick_params(axis="x", labelsize=14)
clean_bars(ax, share_early)
ax.set_xlabel("Revenue share of the 169 biggest early spenders", color=MUTED, fontsize=13, labelpad=8)
save("c3_fade")

# Slide 4: same demand at every price, very different revenue
fig, axes = plt.subplots(1, 2, figsize=SIZE)
labels = ["$0.99", "$2.99", "$4.99"]
for ax, col, fmt, title, cols in [
        (axes[0], "rentals_per_title", "{:.1f}", "Rentals per film", [BLUE] * 3),
        (axes[1], "revenue_per_title", "${:,.0f}", "Revenue per film", [BLUE, BLUE, ORANGE])]:
    b = ax.bar(labels, tiers[col], color=cols, width=0.62)
    ax.bar_label(b, labels=[fmt.format(v) for v in tiers[col]], padding=6, fontsize=19, fontweight="bold")
    clean_bars(ax, tiers[col].max())
    ax.set_title(title, fontsize=18, fontweight="bold", pad=12)
save("c4_price")

# Slide 5: share of rentals extended, by rental window (3-day in orange)
ext_rate = df.groupby("rental_duration").extended.mean()
fig, ax = plt.subplots(figsize=SIZE)
b = ax.bar([f"{d}-day" for d in ext_rate.index], ext_rate, color=[ORANGE] + [BLUE] * 4, width=0.62)
ax.bar_label(b, labels=[f"{v:.0%}" for v in ext_rate], padding=6, fontsize=19, fontweight="bold")
clean_bars(ax, ext_rate.max())
note(ax, "Share of rentals that paid to extend, by rental window")
save("c5_extensions")

# Slide 6: filmmaker earnings by genre (top 3 in orange)
gs = genre.filmmaker_per_title.sort_values()   # gs, so Step 7's g stays intact
fig, ax = plt.subplots(figsize=SIZE)
b = ax.barh(gs.index, gs, color=[ORANGE if i >= len(gs) - 3 else BLUE for i in range(len(gs))], height=0.68)
ax.bar_label(b, labels=[f"${v:.0f}" for v in gs], padding=5, fontsize=18, fontweight="bold")
ax.set_xlim(0, gs.max() * 1.14)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=18)
ax.spines["bottom"].set_visible(False)
ax.spines["left"].set_visible(True)
note(ax, "Filmmaker earnings per title (75% share)")
save("c6_genres")

# Slide 7: customers per million internet users (from Step 7), Spanish-speaking in orange
m = big.sort_values("per_m_users")
fig, ax = plt.subplots(figsize=SIZE)
b = ax.barh([n.replace("Russian Federation", "Russia") for n in m.index], m.per_m_users,
            color=[ORANGE if s else BLUE for s in m.spanish], height=0.68)
for t in ax.bar_label(b, labels=[f"{v:.2f}" for v in m.per_m_users], padding=5, fontsize=18, fontweight="bold"):
    t.set_bbox(dict(facecolor="white", edgecolor="none", pad=1.5))   # keeps labels readable over the dashed line
ax.axvline(us_rate, color=MUTED, linestyle="--", linewidth=1.5, zorder=0)
ax.text(us_rate, len(m) - 0.35, " US rate", color=MUTED, fontsize=17, va="bottom")
ax.set_xlim(0, m.per_m_users.max() * 1.15)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=18)
ax.spines["bottom"].set_visible(False)
ax.spines["left"].set_visible(True)
note(ax, "ReelIndie customers per million internet users (orange = Spanish-speaking)")
save("c7_market")

# Slide 7 inset: Spanish-speaking vs everyone else (the 2.4x)
fig, ax = plt.subplots(figsize=(4.5, 1.74))      # drawn at the size it appears on the slide
vals = [g.per_m[False], g.per_m[True]]
b = ax.barh(["Everyone else", "Spanish-speaking"], vals, color=[BLUE, ORANGE], height=0.62)
ax.bar_label(b, labels=[f"{v:.2f}" for v in vals], padding=4, fontsize=19, fontweight="bold")
ax.set_xlim(0, max(vals) * 1.35)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=17)
ax.spines["bottom"].set_visible(False)
ax.spines["left"].set_visible(True)
ax.set_xlabel("Customers per million internet users", color=MUTED, fontsize=12, labelpad=4)
plt.tight_layout(pad=0.3)
plt.savefig("deck_charts/c7b_spanish.png", dpi=300, bbox_inches="tight")
plt.close()
print("saved c7b_spanish")
