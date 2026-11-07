# Real UzEx market data — sources and caveats

Collected 2026-11-07. Every number in `real_market.json` was read from one of the sources below. Nothing is interpolated or invented.

## Primary source: uzex.uz public JSON (no auth)

- **`https://uzex.uz/Quote/GetDynamics/{hash}`** returns `{"name": ..., "model": [[epoch_ms, price], ...]}`. This is the data behind the "Динамика котировок" chart at https://uzex.uz/Quote/QuotesDynamics. The points are weekly and dated to the end of the week (usually Friday). Some series go back to 2014. The product hashes come from the `data-hash` attribute on the table rows of `/Quote/QuotesDynamics?Search=<text>&length=100`.
- **`https://uzex.uz/Quote/GetQuotes`** is the homepage ticker: about 27 headline products with their current price and change. It has no date, so I recorded those points as "fetched 2026-11-07".
- `https://uzex.uz/Quote/GetQuotesDayly` is a daily ticker for about 22 products, but it was **not used**. It gives only day-of-month labels with no month, and its prices look like UZS/kg (cement 486.71, rebar 8201), so the unit is ambiguous.
- Trade pages such as `/Trade/ContractsSumNew` (lots with base price, seller and warehouse) are server-rendered HTML. I did not scrape them because the site was slow. They are the place to get **seller names and lot volumes**.
- The site is slow and flaky. Searches often time out or return HTTP 500, especially multi-word ones. Single words work best. In total I made about 50 requests.

## What was found

| key | UzEx product | points | range |
|---|---|---|---|
| lpg | Сжиженный газ | weekly + 3 daily (Spot.uz) + ticker | 2024-01 → 2026-10-30 |
| gasoline_ai92 | Автобензин А-92 (тонна) | weekly + ticker | 2024-01 → 2026-10-30 |
| cement | Портландцемент II/А-И 42,5 Н (навал) | weekly | 2024-01 → 2026-10-30 |
| cement_325 | Портландцемент II/А-И 32,5 Н (навал) | weekly + ticker | 2024-01 → 2026-10-30 |
| polypropylene | Полипропилен Y130 | weekly + ticker (Y130, B-310) | 2024-01 → 2026-10-09 |
| wheat | Пшеница 3 класс | weekly + ticker | 2024-01 → 2026-10-30 |
| flour | Мука пшеничная 1 сорт / хлебопекарная 1 сорт | weekly + ticker | 2024-01 → 2025-08-15, then ticker only |
| sugar | Сахар-песок категории ТС-2 | weekly | 2024-01 → 2026-10-23 |
| urea | Карбамид «Б» (в мешках) | weekly | 2024-01 → 2026-10-30 |
| copper_cathode | Медь катодная | weekly + ticker | 2024-01 → 2026-10-30 |
| rebar | Арматура 12мм Ст35ГС мерной длины; А500С ф10/ф14 | sparse (28) | 2025-03 → 2026-10-16 + ticker |
| cottonseed_oil | Масло хлопковое раф. дезод. 1 сорт прессовое | 4 (2023, «МАСЛОВ» lot) + ticker | sparse |

**Propane spike, checked against the source.** https://www.spot.uz/ru/2026/09/21/propane/ citing UzEx trade data:
- 16 Sep 2026: 7.412 mln UZS/t
- 17 Sep 2026: 11.904 mln UZS/t (+60.6%)
- 18 Sep 2026: 12.217 mln UZS/t (+2.6%)
- The 10% price-growth cap was removed on 17 Sep. The 7.5 mln UZS/t limit on seller starting prices still applies.
- Over these days the volume rose from 666 t to 1114 t. That is an aggregate, not a per-day figure, so it is in the point's note only.

The UzEx weekly series shows the same move: 6.56 mln (09-04) → 9.76 mln (09-18) → 11.60 mln (09-25) → 10.37 mln (10-30).

## Not found or caveats

- **Exact grades:** I found no recent UzEx series for "ЦЕМ I 42,5Н / М400" or for "А500С" beyond 4 points in 2025. I used the closest liquid grades instead.
- **AI-80:** no series was pulled. "Бензин" searches returned HTTP 500. The daily ticker shows "БЕНЗИН (80)" at 11 137.53 (apparently per kg, undated), but it was not included.
- **Volume and seller:** the GetDynamics endpoint does not expose them. All `volume`/`seller` fields are null.
- **Price basis:** I did not verify whether the price is a weekly weighted average or the last price. VAT inclusion was also not verified; UzEx base prices are generally quoted VAT-inclusive, but no page I fetched states this.
- **Mixed product lines:** some series mix grades (rebar, flour). Each point's `note` and `source` hash identify the exact product.
- **Units:** all prices are UZS per тонна, as labelled on QuotesDynamics. Gasoline also has a per-litre product (`Автобензин А-92 (литр)`), which was not pulled.
- **Not attempted (time):** data.egov.uz, stat.uz, UzEx PDF bulletins.
- **`name_uz` values:** taken from the UzEx Uzbek ticker where available (lpg, gasoline, cement_325, rebar, PP, wheat, flour, copper, cotton oil). For sugar, urea and cement 42.5 I transliterated the name myself; those are not official names.
