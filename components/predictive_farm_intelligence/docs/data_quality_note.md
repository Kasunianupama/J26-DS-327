# Farm X aggregate data-quality note

All figures in this note are anonymous aggregates supplied by the user. No database was
accessed to prepare it, and no animal identifiers or row-level records are included.

## Executive summary

| Data area | Time available | Coverage volume | Main quality finding |
|---|---:|---:|---|
| Observed milk yield | 7 calendar years; 67 months | 1,585 observed days; 861,675 cow-days | Broad historical volume, but incomplete daily cow coverage |
| Milking sensors | 12 months across 2 calendar years | 295 days; 79,325 sessions; 674 linked cows | Excellent yield overlap during the sensor era, but the first year is only a pilot-sized sample |
| Calving and reproduction | 12 calendar years | 13,497 calvings; 87,203 inseminations | Long history; conception and dry-off completeness deteriorate in recent records |
| Disease episodes | 12 calendar years | 3,651 episodes; 46 raw labels; 678 active days | Intermittent recording concentrated in the early years |
| Treatments | 7 calendar years | 15,290 records; 8 labels; 203 active days | Strongly concentrated into batch or campaign days |
| Vaccinations | 5 calendar years | 13,627 records; 45 active days | Campaign-style data; vaccination type is unavailable |
| THI and weather | Nov 2015 to Oct 2026 | 132 months; up to 4,018 calendar days | Long overlapping span; actual daily completeness still requires the annual THI check |

## 1. Observed milk yield

- Usable yield occurs in 67 months across parts of 7 calendar years.
- There are 1,585 distinct days with usable yield and 861,675 observed cow-days.
- This averages 23.7 yield-recording days per covered month and approximately 544
  observed cows per yield-recording day.
- A cow-day means one cow with a yield observation on one day; it is not a count of
  unique cows.
- The supplied results do not include the total number of unique cows with any
  historical yield. Query 1 in `docs/sql/descriptive_data_availability.sql` returns it as
  `cows_with_usable_yield`.

### Milk-record gaps

The reconstructed milking panel covers 133 months and 4,038 expected milking days.

| Gap measure | Days | Share of expected days |
|---|---:|---:|
| Farm-wide yield gap | 948 | 23.5% |
| Partial or cow-level gap | 3,090 | 76.5% |
| Fully observed lactation day | 0 | 0.0% |
| Sparse-record day | 663 | 16.4% |
| No usable milk target | 1,384 | 34.3% |

Sparse and no-usable classifications can overlap the farm-wide and partial categories,
so those counts must not be added together. Mean monthly observed-versus-expected cow
coverage is approximately 3.35%. The per-cow milk history therefore represents a sample
of the milking herd rather than a complete daily census. Missingness is predominantly
partial or cow-specific, although farm-wide outages are also substantial.

## 2. Milking sensors and overlap with yield

Sensor data contains eight session fields, 79,325 sessions, 295 active days and 674
linked cows. This is approximately 269 sessions per sensor-active day and 1.72 sessions
per sensor cow-day.

During the sensor era:

- Yield exists on 292 days, and sensors exist on every one of those days.
- 290 days have full cow-level overlap and 2 have partial overlap.
- There are no farm-wide sensor gaps on yield-active days.
- Three additional days contain sensors but no usable yield.
- 45,752 of 45,779 yield cow-days match sensor data (99.94%).
- 45,752 of 46,194 sensor cow-days match yield data (99.04%).

Across the complete yield history, only 5.31% of yield cow-days overlap sensors because
sensors cover only the most recent 12 months. This is a time-span limitation, not poor
matching during the sensor era.

### Sensor inventory

| Sensor or measurement | Total | Per 100 sessions |
|---|---:|---:|
| Recorded session yield | 79,325 | 100.0 |
| Expected session yield | 79,325 | 100.0 |
| Blood alarms | 1,583 | 2.0 |
| Conductivity alarms | 4,327 | 5.5 |
| Kick-offs | 10,067 | 12.7 |
| Reattaches | 26,703 | 33.7 |
| Manual-detach flags | 37,150 | 46.8 |
| Low-yield flags | 24,412 | 30.8 |

Kick-offs and reattaches are event totals, so one session may contain more than one.

### Sensors by year

| Year | Session records | Days with values | Linked cows |
|---:|---:|---:|---:|
| 2025 | 448 | 109 | 11 |
| 2026 | 78,877 | 186 | 670 |
| **Total** | **79,325** | **295** | **674 distinct overall** |

Annual cow counts are not additive because a cow can occur in both years. The first
sensor year averages only 4.1 sessions per active day. The second contains 99.4% of all
sessions and averages approximately 424 sessions per active day, so the two years belong
to different recording regimes.

| Sensor type | 2025 | 2026 | Total |
|---|---:|---:|---:|
| Blood alarms | 21 | 1,562 | 1,583 |
| Conductivity alarms | 29 | 4,298 | 4,327 |
| Kick-offs | 65 | 10,002 | 10,067 |
| Low-yield flags | 141 | 24,271 | 24,412 |
| Manual-detach flags | 335 | 36,815 | 37,150 |
| Reattaches | 242 | 26,461 | 26,703 |
| Recorded-yield measurements | 448 | 78,877 | 79,325 |
| Expected-yield measurements | 448 | 78,877 | 79,325 |

| Sensor type | 2025 per 100 sessions | 2026 per 100 sessions |
|---|---:|---:|
| Blood alarms | 4.7 | 2.0 |
| Conductivity alarms | 6.5 | 5.4 |
| Kick-offs | 14.5 | 12.7 |
| Low-yield flags | 31.5 | 30.8 |
| Manual-detach flags | 74.8 | 46.7 |
| Reattaches | 54.0 | 33.5 |

Recorded and expected yield are populated for every sensor session. Differences between
the two years, particularly manual detaches and reattaches, must not be interpreted as
biological or operational improvement without accounting for the change from 11 to 670
linked cows. The first year is best treated as pilot or partial coverage; the second is
suitable for descriptive session-level analysis.

## 3. Calving and reproductive history

The reproductive history spans 12 calendar years, with partial coverage in the first and
latest years.

| Measure | Aggregate count |
|---|---:|
| Calvings | 13,497 |
| Conception histories | 10,406 |
| Dry-off histories | 11,231 |
| Service-count histories | 13,497 |
| Recorded aborted lactations | 781 |
| Inseminations | 87,203 |
| Days containing inseminations | 4,097 |
| Calves recorded | 13,512 |
| Days containing calf records | 3,445 |

Completeness relative to calvings is 77.1% for conception, 83.2% for dry-off and 100%
for the presence of a service-count field. Recorded aborted lactations are approximately
5.8% of calvings, and the dataset contains approximately one calf per calving.

The 13,350 annual cow-calving counts and 23,551 annual cow-insemination counts are
cow-year sums, not unique cows over the complete history. Earlier reproductive history
is comparatively complete. Some deterioration in the latest period is expected
right-censoring: recently calved cows may not yet have conceived, been confirmed pregnant
or reached dry-off.

## 4. Disease episodes

The dataset contains 3,651 disease episodes across 46 raw labels and 678 active days,
averaging 5.4 episodes on days when disease recording occurs.

| Recorded type | Episodes | Share |
|---|---:|---:|
| Broad mastitis label | 1,533 | 42.0% |
| Other or unknown | 1,198 | 32.8% |
| Deworming | 480 | 13.1% |
| Blind-teat condition | 178 | 4.9% |
| Mastitis | 108 | 3.0% |
| Wounds and injuries | 18 | 0.5% |
| Other-cause lameness | 15 | 0.4% |
| Metritis | 15 | 0.4% |
| Per-acute mastitis | 11 | 0.3% |
| Udder abscess | 11 | 0.3% |
| Remaining 36 labels | 84 | 2.3% |

The five largest labels contain approximately 95.8% of all episodes.

### Annual disease availability

| Year | Episodes | Distinct raw types | Dominant recorded type |
|---:|---:|---:|---|
| 2015 | 800 | 10 | Broad mastitis label: 648 |
| 2016 | 1,477 | 13 | Other/unknown: 947; broad mastitis: 511 |
| 2017 | 916 | 37 | Deworming: 480; broad mastitis: 263 |
| 2018 | 128 | 4 | Broad mastitis: 97 |
| 2019 | 28 | 3 | Broad mastitis: 14 |
| 2020 | 114 | 3 | Blind-teat condition: 60; mastitis: 53 |
| 2021 | 112 | 7 | Blind-teat condition: 67; mastitis: 32 |
| 2022 | 35 | 2 | Blind-teat condition: 23; mastitis: 12 |
| 2023 | 36 | 3 | Blind-teat condition: 28; mastitis: 7 |
| 2024 | 0 | 0 | No disease records |
| 2025 | 0 | 0 | No disease records |
| 2026 | 5 | 1 | Other/unknown: 5 |

Disease recording is concentrated in the early history: 87.5% of all episodes occur in
2015–2017. Records exist in 10 of 12 years, while two complete years have none. This is a
recording gap, not evidence that no disease occurred. Raw-label diversity drops sharply
after 2017. Mastitis-related conditions dominate meaningful diagnoses; deworming is a
preventive activity stored among disease episodes; and spelling or wording variants split
equivalent conditions. Analysis should therefore use reviewed health groups instead of
all 46 raw labels independently.

## 5. Treatments and vaccinations

| Type | Records | Raw labels | Active days | Mean per active day |
|---|---:|---:|---:|---:|
| Treatments | 15,290 | 8 | 203 | 75.3 |
| Vaccinations | 13,627 | 1 | 45 | 302.8 |

One treatment label is unspecified and covers 253 records. Every vaccination-table
record has an unspecified vaccination label, so campaign timing and size are usable but
vaccine-specific comparisons are not.

### Annual availability

| Year | Treatment records | Treatment types | Vaccination records |
|---:|---:|---:|---:|
| 2018 | 0 | 0 | 5,733 |
| 2019 | 0 | 0 | 19 |
| 2020 | 153 | 2 | 0 |
| 2021 | 15,041 | 8 | 7,381 |
| 2022 | 51 | 3 | 494 |
| 2023 | 40 | 2 | 0 |
| 2024 | 0 | 0 | 0 |
| 2025 | 0 | 0 | 0 |
| 2026 | 5 | 1 | 0 |

Approximately 98.4% of treatment records occur in one year. Vaccination records are
also campaign-based: 42.1% occur in 2018 and 54.2% in 2021. These data describe bulk
preventive campaigns more reliably than continuous individual clinical treatment.

## 6. THI and weather coverage

THI records are available from November 2015 through October 2026. This represents 132
calendar months, parts of 12 calendar years and an 11-year continuous calendar span. If
every day is present, the range can contain at most 4,018 daily records.

The THI span overlaps most milk-yield, reproductive, disease and herd-history coverage,
making it suitable for temporal comparison. The date range alone does not confirm that
all daily values are complete. Query 14 in `docs/sql/descriptive_data_availability.sql`
reports annual weather rows, complete days, days with mean and maximum THI, days with
hours-above-threshold values and completeness percentages.

## 7. Important limitations and recommended use

1. Historical per-cow milk is a sample, not a complete daily herd census.
2. Recent sensor-to-yield matching is excellent, but sensor history is only 12 months.
3. The two sensor years have very different population coverage and must not be compared
   without accounting for the recording-regime change.
4. Conception and dry-off completeness deteriorate in recent reproductive records;
   right-censoring explains part, but not necessarily all, of the decline.
5. Absence of disease records must not be interpreted as absence of disease.
6. Disease labels need consolidation into reviewed clinical groups.
7. Treatment and vaccination records primarily represent campaign activity.
8. Vaccination type is unavailable in the current published table.
9. The pasted daily health and sensor extracts were capped at 400 rows and are incomplete
   previews; full-history daily distributions must use uncapped aggregate exports.
10. THI has a long nominal date range, but annual daily completeness still needs to be
    confirmed with Query 14.

## Reproducibility

The aggregate-only SQL used for this note is in
[`docs/sql/descriptive_data_availability.sql`](sql/descriptive_data_availability.sql).
It is read-only and returns counts, distributions and date coverage without returning
animal identifiers.
