-- =====================================================================
-- ReelIndie: the Python analysis rebuilt as Access queries
-- HOW TO ADD EACH QUERY:
--   Create > Query Design > close the "Show Table" box > SQL View (top-left)
--   > delete what's there > paste ONE query > Run (red !) > Save with the
--   name shown above it (exact name: later queries use earlier ones).
-- Build them IN ORDER. Dates before 1/1/2025 only: this skips the 182
-- odd rentals all stamped June 14, 2025.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. qryRentalDetail  (the base table every other query uses)
--    ext_fee = what they paid above the listed rental rate ($1/day over)
-- ---------------------------------------------------------------------
SELECT r.rental_id, r.rental_date, r.return_date, r.customer_id, r.film_id,
       f.title, f.rental_rate, f.rental_duration, f.rating, c.[name] AS category,
       p.amount,
       IIf(p.amount > f.rental_rate, Round(p.amount - f.rental_rate, 2), 0) AS ext_fee,
       IIf(p.amount > f.rental_rate, 1, 0) AS extended
FROM (((rental AS r
   INNER JOIN payment AS p ON r.rental_id = p.rental_id)
   INNER JOIN film AS f ON r.film_id = f.film_id)
   INNER JOIN film_category AS fc ON f.film_id = fc.film_id)
   INNER JOIN category AS c ON fc.category_id = c.category_id
WHERE r.rental_date < #1/1/2025#;


-- =====================================================================
-- FINDING: EXTENSION FEES = 30% OF REVENUE
-- =====================================================================

-- 2. qryExtensionTotal   (expect ~$66,892 total, ~$20,195 fees, 30%, 46%)
SELECT Sum(amount) AS total_revenue,
       Sum(ext_fee) AS extension_fees,
       Sum(ext_fee) / Sum(amount) AS fee_share_of_revenue,
       Avg(extended) AS pct_rentals_extended
FROM qryRentalDetail;

-- 3. qryExtensionByWindow   (expect 67% at 3 days down to 23% at 7 days)
SELECT rental_duration AS window_days,
       Count(*) AS rentals,
       Avg(extended) AS pct_extended,
       Avg(ext_fee) AS avg_fee
FROM qryRentalDetail
GROUP BY rental_duration
ORDER BY rental_duration;


-- =====================================================================
-- FINDING: PRICE DOESN'T CHANGE DEMAND
-- =====================================================================

-- 4. qryTierTitles   (films that were rented, per price tier)
SELECT rental_rate, Count(*) AS titles
FROM (SELECT DISTINCT film_id, rental_rate FROM qryRentalDetail) AS x
GROUP BY rental_rate;

-- 5. qryPriceTiers   (expect ~17 / 16 / 16 rentals per title; $40 / $68 / $102 revenue)
SELECT d.rental_rate, t.titles,
       Count(*) AS rentals,
       Sum(d.amount) AS revenue,
       Count(*) / t.titles AS rentals_per_title,
       Sum(d.amount) / t.titles AS revenue_per_title
FROM qryRentalDetail AS d
INNER JOIN qryTierTitles AS t ON d.rental_rate = t.rental_rate
GROUP BY d.rental_rate, t.titles
ORDER BY d.rental_rate;

-- 6. qryPriceWhatIf   UPDATED for deck v10
--    (expect 5,583 rentals, ~$7,535 fees, +$11,166 no drop, ~ +$1,475 if 40% leave, break-even 0.46)
--    Renters who leave also stop paying extension fees, so those count too.
--    If you already saved the old version, open it in SQL View and replace it with this.
SELECT Count(*) AS rentals_at_099,
       Sum(ext_fee) AS ext_fees_at_099,
       Count(*) * (2.99 - 0.99) AS added_revenue_no_demand_drop,
       (Count(*) * 2.99 + Sum(ext_fee)) * 0.6 - (Count(*) * 0.99 + Sum(ext_fee)) AS added_revenue_if_40pct_leave,
       1 - (Count(*) * 0.99 + Sum(ext_fee)) / (Count(*) * 2.99 + Sum(ext_fee)) AS breakeven_share_leaving
FROM qryRentalDetail
WHERE rental_rate = 0.99;


-- =====================================================================
-- FINDING: NO NEW CUSTOMERS AFTER OCTOBER
-- =====================================================================

-- 7. qryFirstRental
SELECT customer_id, Min(rental_date) AS first_rental
FROM qryRentalDetail
GROUP BY customer_id;

-- 8. qryNewCustomersByMonth   (expect 520 Sep, 78 Oct, 1 Nov, 0 Dec)
SELECT Format(first_rental, "yyyy-mm") AS first_month,
       Count(*) AS new_customers
FROM qryFirstRental
GROUP BY Format(first_rental, "yyyy-mm")
ORDER BY Format(first_rental, "yyyy-mm");

-- 9. qryRevenueByMonth   (November holds TWO of the five snapshot weeks)
SELECT Format(rental_date, "yyyy-mm") AS rental_month,
       Count(*) AS rentals,
       Sum(amount) AS revenue
FROM qryRentalDetail
GROUP BY Format(rental_date, "yyyy-mm")
ORDER BY Format(rental_date, "yyyy-mm");


-- =====================================================================
-- FINDING: WHAT FILMMAKERS EARN BY GENRE
-- =====================================================================

-- 10. qryCategoryTitles   (all films per genre, including never-rented)
SELECT c.[name] AS category, Count(*) AS titles
FROM film_category AS fc
INNER JOIN category AS c ON fc.category_id = c.category_id
GROUP BY c.[name];

-- 11. qryCategoryEconomics   (expect Sci-Fi ~$58 to Foreign ~$44 per title)
SELECT d.category, t.titles,
       Count(*) AS rentals,
       Sum(d.amount) AS revenue,
       Sum(d.amount) / t.titles AS revenue_per_title,
       Sum(d.amount) * 0.75 / t.titles AS filmmaker_earns_per_title
FROM qryRentalDetail AS d
INNER JOIN qryCategoryTitles AS t ON d.category = t.category
GROUP BY d.category, t.titles
ORDER BY Sum(d.amount) / t.titles DESC;


-- =====================================================================
-- CUSTOMER SEGMENTS (rule-based; Access has no k-means)
-- Close to the Python result for Superfans (~159 customers, ~33% of revenue).
-- Deck v10 slide 3: the segments DON'T LAST over time; queries 20-22 below check that.
-- =====================================================================

-- 12. qryCustomerSummary
SELECT customer_id,
       Count(*) AS rentals,
       Sum(amount) AS spend,
       Avg(rental_rate) AS avg_price,
       Avg(extended) AS pct_extended
FROM qryRentalDetail
GROUP BY customer_id;

-- 13. qryCustomerSegments
SELECT customer_id, rentals, spend, avg_price, pct_extended,
       Switch(rentals >= 30, "Superfans",
              pct_extended >= 0.55, "Binge-keepers",
              avg_price < 2.7, "Bargain hunters",
              True, "On-time watchers") AS segment
FROM qryCustomerSummary;

-- 14. qrySegmentSummary
SELECT segment, Count(*) AS customers, Sum(spend) AS revenue,
       Avg(rentals) AS avg_rentals, Avg(pct_extended) AS avg_pct_extended
FROM qryCustomerSegments
GROUP BY segment
ORDER BY Sum(spend) DESC;


-- =====================================================================
-- OUTSIDE DATA: WORLD BANK (internet users by country)
-- First import it: External Data > New Data Source > From File > Excel >
--   pick ReelIndie_analysis_tables.xlsx (made by the Python script) >
--   "Import into a new table" > sheet "Countries" > tick "First Row Contains
--   Column Headings" > no primary key > name the table tblWorldBank.
-- (Or download "Individuals using the Internet" and "Population, total"
--  from data.worldbank.org as Excel and import those instead.)
-- =====================================================================

-- 15. qryCountryCustomers
SELECT co.country, Count(cu.customer_id) AS customers
FROM ((customer AS cu
   INNER JOIN address AS a ON cu.address_id = a.address_id)
   INNER JOIN city AS ci ON a.city_id = ci.city_id)
   INNER JOIN country AS co ON ci.country_id = co.country_id
GROUP BY co.country;

-- 16. qryMarketPenetration   (customers per million internet users, biggest markets first)
SELECT q.country, q.customers, w.internet_users_m,
       q.customers / w.internet_users_m AS customers_per_m_internet_users,
       w.spanish_speaking
FROM qryCountryCustomers AS q
INNER JOIN tblWorldBank AS w ON q.country = w.country
WHERE w.internet_users_m Is Not Null
ORDER BY w.internet_users_m DESC;

-- 17. qrySpanishVsOther   (expect ~0.23 vs ~0.10: Spanish-speaking is ~2.4x)
SELECT spanish_speaking,
       Sum(customers) AS total_customers,
       Sum(internet_users_m) AS internet_users_millions,
       Sum(customers) / Sum(internet_users_m) AS customers_per_m
FROM qryMarketPenetration
GROUP BY spanish_speaking;


-- =====================================================================
-- NEW FOR DECK v10
-- =====================================================================

-- 19. qryExtensionOption   (slide 5: "+3 days" at checkout, $1.99 vs $2.99)
--     Kept 1-3 extra days -> pays the option (or their old fee if cheaper);
--     kept longer -> option + $1/day after day 3.
--     (expect ~$20,195 today; ~$16,485 at $1.99 = ~$3,700 less; ~$20,158 at $2.99 = about even)
SELECT Sum(ext_fee) AS fees_today,
       Sum(IIf(ext_fee <= 3, IIf(ext_fee < 1.99, ext_fee, 1.99), 1.99 + ext_fee - 3)) AS fees_at_199,
       Sum(IIf(ext_fee <= 3, IIf(ext_fee < 2.99, ext_fee, 2.99), 2.99 + ext_fee - 3)) AS fees_at_299,
       Sum(IIf(ext_fee <= 3, IIf(ext_fee < 1.99, ext_fee, 1.99), 1.99 + ext_fee - 3)) - Sum(ext_fee) AS change_at_199,
       Sum(IIf(ext_fee <= 3, IIf(ext_fee < 2.99, ext_fee, 2.99), 2.99 + ext_fee - 3)) - Sum(ext_fee) AS change_at_299
FROM qryRentalDetail
WHERE extended = 1;

-- 20. qryEarlyTop169   (slide 3: the 169 biggest spenders in the early weeks, Sep 21 - Nov 9)
SELECT TOP 169 customer_id, Sum(amount) AS early_spend
FROM qryRentalDetail
WHERE rental_date < #11/15/2024#
GROUP BY customer_id
ORDER BY Sum(amount) DESC;

-- 21. qryLateTop169   (what those same 169 spent in the late weeks, Nov 23 - Dec 21; expect ~$11,150)
SELECT Sum(d.amount) AS late_spend
FROM qryRentalDetail AS d
INNER JOIN qryEarlyTop169 AS t ON d.customer_id = t.customer_id
WHERE d.rental_date >= #11/15/2024#;

-- 22. qryEarlyLateShare   (slide 3: expect early 0.39, late 0.29, share of customers 0.28)
--     Set all three columns to Percent in the property sheet.
SELECT DSum("early_spend", "qryEarlyTop169") / DSum("amount", "qryRentalDetail", "rental_date < #11/15/2024#") AS early_share,
       DLookUp("late_spend", "qryLateTop169") / DSum("amount", "qryRentalDetail", "rental_date >= #11/15/2024#") AS late_share,
       169 / 599 AS share_of_customers;

-- NOT IN ACCESS: the correlations (r = 0.04, 0.07), the regressions (3.5%, genre 1.4%)
-- and k-means. Access can't run those; they come from Python (Steps 4-6).
