# Vegetation QA/QC: Handover to the Tech Team

This document specifies how to run the herbaceous vegetation quality checks automatically on NS Analytics. The pipeline starts when the raw ODK tables arrive. It produces clean tables, a list of flagged problems, and a Vegetation QA/QC dashboard with the same content as the [data quality report](vegetation_data_quality_report.md).

The report's section "How the survey works" explains plots, quadrats and species codes. The reference implementation is [notebooks/vegetation.ipynb](../../../notebooks/vegetation.ipynb), and the sample data in `data/raw/vegetation/` can serve as the test fixture.

## 1. Principles

1. **Flag, never fix.** Raw tables are read-only. Every problem becomes a row in one flags table. Corrections happen at the source, in ODK review or the entity lists, and the next run picks them up.
2. **One generic flags table.** Every check writes rows of the same shape. Adding a check means adding one query, not a new table or dashboard widget.
3. **Rules come from the SOPs.** Every threshold is a per-project setting with the SOP value as its default (section 6).
4. **Recompute the whole project on each run.** A baseline is about 30 surveys and 640 quadrats, so a full rebuild takes seconds. It also avoids stale flags after a submission is edited or rejected.

## 2. Pipeline

| Step | What happens | Where |
|---|---|---|
| 1. Trigger | A survey or registration is submitted or edited, or an entity list changes. Queue one job per project. | Existing ODK sync |
| 2. Schema check | Confirm the expected columns exist for this form version. If not, stop with a message naming the missing columns. | Python |
| 3. Clean and join | Build the clean tables in section 4. | PostgreSQL views, with PostGIS for distances |
| 4. Checks | Delete the project's old flags and write new ones (section 5). | One SQL statement per check. GBIF lookup in Python |
| 5. Summaries | Build the survey, plot and sampling-effort tables. | SQL views. Chao2 and accumulation curves in Python |
| 6. Dashboard | Serve read-only views to the front end (section 7). | React |

Running the job twice must give the same result. If the schema check fails, the dashboard keeps the previous results and shows a "stale data" banner. Bad values never stop the job, because they become flags.

## 3. Input tables

| Table | One row is | Links to |
|---|---|---|
| Survey (`herbaceous_veg_survey`) | One survey submission | The plot entity, through the selected plot ID |
| Quadrat repeat | One quadrat, 20 per survey | Its survey, through `PARENT_KEY` |
| Additional-species repeat | One species not picked from the list | Its quadrat, through `PARENT_KEY` |
| Plot registration (`register_vegetation_plots`) | One plot registration with transect GPS points | The planned plot, through the selected plot ID |
| Entity `vegplots` | One registered plot, as offered in the survey form | The planned plot, through `plot_uuid` |
| Entity `centroids` | One planned plot: GPS point, stratum, primary or backup | |
| Entity `species` | One species on the project list | |
| Entity `species_extra` | One species added in the field, missing or unknown | |
| Entity `species_extra_ids` | The later identification of a provisional code | `species_extra`, through the provisional code |

## 4. Clean tables

**Species records** are the core table, with one row per species per quadrat. Species reach the data in two ways:

1. **Picked from the list.** The quadrat stores the IDs of all selected species in one space-separated field. Split it into one row per ID and look each ID up in `species`.
2. **Added in the field.** Each additional-species row points to a `species_extra` entity. The pointer is in one of three columns, depending on how the species was entered: `target_extra_name` for a new entry, or `select_reuse_unknown` or `select_reuse_missing` for a reused one. Take the first one that is filled. The provisional code is `herb_` plus the entity's `unknown_index` padded to three digits, for example `herb_007`. Look that code up in `species_extra_ids` to get the identified name.

The **resolved name** is the identified name. While the name is missing or "Unknown", use the provisional code instead, so an unidentified species still counts as one taxon. The only clean-up applied is trimming spaces. Do not parse the display columns joined with `<br/>`, such as `species_list-all_species_list`. They mix codes and names and cannot be joined reliably.

**Plot geometry.** Store all GPS points as geographic points in WGS84, the coordinate system ODK uses. From them, compute:

- the distance in metres from the recorded midpoint to the planned point, and from each endpoint to the midpoint
- the bearing from endpoint A to endpoint B, folded into 0–180°, where 0° is north–south
- for each quadrat, the distance to the midpoint and to the line from endpoint A to endpoint B.

**Rejected submissions** stay in every table, marked as rejected. They are excluded from every count and richness value.

## 5. Checks

Every check writes rows with these fields:

| Field | Content |
|---|---|
| Project, run ID, created at | Which run produced the flag |
| Check ID | For example `P02`. Links to the check catalogue. |
| Level | Survey, plot, quadrat or species |
| Severity | Error, warning or info |
| Record key | The flagged record: ODK key, entity ID or species name |
| Plot name | So every flag can be filtered by plot |
| Detail | The observed value in words, for example "midpoint 34 m from planned point" |

A small static table holds the check catalogue: ID, description, severity, rule and source. The full list of 24 checks, with their rules and counts on the sample data, is in the [report appendix](vegetation_data_quality_report.md#appendix-checks). The reference notebook currently implements 13 of them. The other 11 are marked there and follow the same pattern.

Severity means:

- **Error.** Data are lost or the protocol was broken. Review it before the data feed any biodiversity metric.
- **Warning.** The value is possible but needs a person to look at it.
- **Info.** Context only, such as a rejected submission or an empty quadrat.

**GBIF name check (T03).** For each new written-out name, call the GBIF species-match service once, with the kingdom set to plants. Store the answer in a lookup table so each name is checked only once. Flag the name when the match is not exact or not at species level, and put GBIF's suggested name in the detail. If GBIF cannot be reached, give unchecked names an info flag and continue.

## 6. Settings per project

| Setting | Default | Source |
|---|---|---|
| Quadrats per plot | 20 | Herbaceous SOP |
| Transect half-length and half-width | 25 m and 2.5 m | 50 m × 5 m belt transect |
| GPS accuracy | 5 m | SOP and form setting |
| Maximum midpoint shift | 25 m | Registration SOP |
| Endpoint tolerance | ±10 m | Assumption: two GPS errors |
| Maximum turn from north–south | 45° | Registration SOP |
| Maximum quadrat offset from the line | 10 m (median per survey) | Assumption |
| Maximum distance of survey end from plot | 100 m | Assumption |
| Plausible survey duration | 30–180 minutes | Assumption |
| Ecosystem types allowed per stratum | Savanna: Scrub or Grassland | Assumption |

Project Delivery should confirm the assumed values.

## 7. Dashboard

One filter bar applies to every tab: project, replicate, stratum, plot, severity and check.

| Tab | Content |
|---|---|
| **Overview** | Tiles for accepted surveys, plots surveyed out of planned, open errors and open warnings. Flag counts by check, which filter the flag list when clicked. |
| **Surveys** | The survey table from report section a. Clicking a row shows its quadrats and flags. |
| **Plots** | The plot table from report section b. |
| **Sampling effort** | Design coverage, accumulation curves and Chao2 completeness, as in report section c. |
| **Map** | Transects and quadrats coloured by their flags, planned points and not-viable plots on a satellite base map, as in report section d. Clicking a plot shows its summary row. |

**Chao2** is the bias-corrected version: observed taxa + ((m − 1) / m) × Q1 × (Q1 − 1) / (2 × (Q2 + 1)). Here m is the number of quadrats, Q1 the number of taxa found in exactly one quadrat, and Q2 the number found in exactly two. For the project level, use plots instead of quadrats. **Accumulation curves** average 200 random orderings with a fixed random seed, so the dashboard does not change between runs.

## 8. Acceptance tests on the sample data

The platform build should reproduce these values.

| Quantity | Expected |
|---|---:|
| Surveys, accepted surveys, quadrats | 32, 30, 640 |
| Species records in accepted surveys | 2,092 |
| Distinct taxa in accepted surveys | 121 |
| Project Chao2 | 159 |
| Plots with midpoint more than 25 m away (`P02`) | Plot 14 only |
| Plots more than 45° off north–south (`P04`) | 30 |
| Quadrats outside the strip (`Q01`) | 33 |
| Quadrats with additional species missing (`Q04`) | 10 |
| Unidentified provisional taxa (`T02`) | 28 |
| Savanna primary plots: planned and surveyed | 30 and 29, plus 1 backup |
| Shrubland primary plots: planned and surveyed | 6 and 0 |

Each check also needs a unit test with one record that should be flagged and one that should not. A schema test should remove a required column and expect the job to stop with a message naming it.

## 9. Open questions for Project Delivery and Biometrics

1. Should an open error stop a survey from feeding biodiversity metrics until it is resolved?
2. Who resolves flags, and should that be stored? I suggest a review table with a status (open, accepted, fixed at source), a comment and the user. The dashboard would then show only open flags by default.
3. Are the assumed settings in section 6 correct?
4. Is "Savanna" missing from the ecosystem types on purpose?
