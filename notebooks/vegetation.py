# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: natural-state (3.13.12)
#     language: python
#     name: python3
# ---

# %%
import pandas as pd
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import json
import urllib.parse
import urllib.request


# %%
# set up
def find_root(marker: str = "pyproject.toml") -> Path:
    path = Path.cwd().resolve()
    while not (path / marker).exists():
        if path.parent == path:
            raise FileNotFoundError(f"No {marker} found above {Path.cwd()}")
        path = path.parent
    return path

ROOT = find_root()
RAW = ROOT / "data" / "raw" / "vegetation" / "ODK Data Exports"
ENT = ROOT / "data" / "raw" / "vegetation" / "Entity lists"
OUT = ROOT / "data" / "raw" / "output" / "vegetation"


# %% [markdown]
# # Read data

# %%
EXPECTED = {
    "herbaceous_veg_survey.csv": ["KEY", "ReviewState", "plot_selection-selected_plot_uuid",
                                  "survey_begin-start_time", "survey_end-end_time"],
    "herbaceous_veg_survey-quadrat_repeat.csv": ["KEY", "PARENT_KEY", "quadrat_number", "herbs_present",
                                                 "location_quadrat-Latitude", "location_quadrat-Longitude"],
    "herbaceous_veg_survey-additional_species_repeat.csv": ["KEY", "PARENT_KEY", "species_entry_mode",
                                                            "target_extra_name", "select_reuse_unknown",
                                                            "select_reuse_missing"],
    "register_vegetation_plots.csv": ["KEY", "plot_selection-selected_plot_uuid",
                                      "plot_selection-is_plot_viable"],
}

# first quality check: are all columns in the CSV as expected
def read(folder, name, expected=()):
    df = pd.read_csv(folder / name)
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")
    return df


survey_raw = read(RAW, "herbaceous_veg_survey.csv", EXPECTED["herbaceous_veg_survey.csv"])
quadrat_raw = read(RAW, "herbaceous_veg_survey-quadrat_repeat.csv",
                   EXPECTED["herbaceous_veg_survey-quadrat_repeat.csv"])
addsp_raw = read(RAW, "herbaceous_veg_survey-additional_species_repeat.csv",
                 EXPECTED["herbaceous_veg_survey-additional_species_repeat.csv"])
reg_raw = read(RAW, "register_vegetation_plots.csv", EXPECTED["register_vegetation_plots.csv"])

# these tables won't be updated frequently, so we're not checking the columns
species = read(ENT, "species.csv")
species_extra = read(ENT, "species_extra.csv")
species_ids = read(ENT, "species_extra_ids.csv")
vegplots = read(ENT, "vegplots.csv")
centroids = read(ENT, "centroids.csv")

# print shapes of all exported tables
for name, df in [("surveys", survey_raw), ("quadrats", quadrat_raw), ("additional species", addsp_raw),
                 ("plot registrations", reg_raw)]:
    print(f"{name:20s} {df.shape}")


# %% [markdown]
# ### Plots: registration, prescribed centroid and transect geometry

# %%
def xy_m(lat, lon, lat0, lon0):
    """Local equirectangular projection in metres around (lat0, lon0). Accurate to < 0.1 % at plot scale."""
    x = (np.asarray(lon) - lon0) * 111_320 * np.cos(np.radians(lat0))
    y = (np.asarray(lat) - lat0) * 110_574
    return x, y


def dist_m(lat1, lon1, lat2, lon2):
    x, y = xy_m(lat1, lon1, lat2, lon2)
    return np.hypot(x, y)


P = "plot_metadata-collect_points-"

# create new data frame for plots
plots = pd.DataFrame({
    "plot_uuid": reg_raw["plot_selection-selected_plot_uuid"],
    "plot_name": reg_raw["plot_selection-plot_name"],
    "plot_status": reg_raw["plot_selection-sample_status"],
    "is_viable": reg_raw["plot_selection-is_plot_viable"],
    "not_viable_reason": reg_raw["plot_selection-plot_establishment_notes"],
    "ecosystem_type": reg_raw["plot_metadata-ecosystem_type_name"],
    "registered_at": pd.to_datetime(reg_raw["survey_begin-start_time"], utc=True),
})

# GPS columns per transect point, e.g. midpoint_lat, midpoint_lon, midpoint_acc.
COORD_SUFFIX = {"Latitude": "lat", "Longitude": "lon", "Accuracy": "acc"}
for point in ["endpoint_a", "midpoint", "endpoint_b"]:
    for coord, suffix in COORD_SUFFIX.items():
        source_col = f"{P}{point}-location_{point}-{coord}"
        plots[f"{point}_{suffix}"] = reg_raw[source_col]

# vegplots is the entity the survey form selects from. Its __id is what surveys reference.
plots = plots.merge(vegplots[["__id", "plot_uuid"]].rename(columns={"__id": "vegplot_id"}), on="plot_uuid",
                    how="left")

# geometry is a space-separated string that starts with "lat lon".
coords = centroids["geometry"].str.split(expand=True)
cent = centroids[["__id", "stratum_label"]].copy()
cent["centroid_lat"] = coords[0].astype(float)
cent["centroid_lon"] = coords[1].astype(float)

plots = plots.merge(cent, left_on="plot_uuid", right_on="__id", how="left").drop(columns="__id")

plots["midpoint_shift_m"] = dist_m(plots["midpoint_lat"], plots["midpoint_lon"],
                                   plots["centroid_lat"], plots["centroid_lon"])
plots["a_to_mid_m"] = dist_m(plots["endpoint_a_lat"], plots["endpoint_a_lon"], plots["midpoint_lat"], plots["midpoint_lon"])
plots["b_to_mid_m"] = dist_m(plots["endpoint_b_lat"], plots["endpoint_b_lon"], plots["midpoint_lat"], plots["midpoint_lon"])
plots["transect_length_m"] = dist_m(plots["endpoint_a_lat"], plots["endpoint_a_lon"],
                                    plots["endpoint_b_lat"], plots["endpoint_b_lon"])
bx, by = xy_m(plots["endpoint_b_lat"], plots["endpoint_b_lon"], plots["endpoint_a_lat"], plots["endpoint_a_lon"])
plots["bearing_deg"] = np.degrees(np.arctan2(bx, by)) % 180  # 0 = north-south, 90 = east-west
plots["bearing_deviation_deg"] = np.minimum(plots["bearing_deg"], 180 - plots["bearing_deg"])

# %%
plots.head()

# %% [markdown]
# #### Plot geometry on a map
#
# Each panel is one plot in local metres, centred on its prescribed centroid (grey +). The grey vertical bar is the
# transect the SOP asks for: 50 m running north-south through the centroid. The dashed circle is the 25 m the midpoint
# may move. The blue line is what the team recorded: endpoint A, midpoint, endpoint B. The dotted line is the midpoint
# shift. The first figure is the plot with the largest shift, labelled, as a guide for reading the grid.

# %%
# Each plot in local metres around its prescribed centroid: where the team was sent (grey) and the
# transect they recorded (blue). Same scale in every panel so shifts and rotations are comparable.
TRANSECT_C, PRESCRIBED_C = "#2a6fdb", "#8c8c8c"
MAX_MIDPOINT_SHIFT_M = 25  # SOP: midpoint may move at most 25 m from the prescribed point
HALF_LENGTH_M = 25  # midpoint to endpoint

def xy_m(lat, lon, lat0, lon0):
    """Local equirectangular projection in metres around (lat0, lon0). Accurate to < 0.1 % at plot scale."""
    x = (np.asarray(lon) - lon0) * 111_320 * np.cos(np.radians(lat0))
    y = (np.asarray(lat) - lat0) * 110_574
    return x, y

def draw_plot(ax, r, annotate=False):
    pts = {p: xy_m(r[f"{p}_lat"], r[f"{p}_lon"], r["centroid_lat"], r["centroid_lon"])
           for p in ["endpoint_a", "midpoint", "endpoint_b"]}
    ax.add_patch(plt.Circle((0, 0), MAX_MIDPOINT_SHIFT_M, fill=False, ls="--", lw=1, color=PRESCRIBED_C))
    ax.plot([0, 0], [-HALF_LENGTH_M, HALF_LENGTH_M], color=PRESCRIBED_C, lw=2, alpha=0.5)  # SOP transect
    ax.plot(0, 0, "+", color=PRESCRIBED_C, ms=10, mew=2)
    (ax_, ay), (mx, my), (bx_, by_) = pts["endpoint_a"], pts["midpoint"], pts["endpoint_b"]
    ax.plot([0, mx], [0, my], ":", color="black", lw=1)  # midpoint shift
    ax.plot([ax_, mx, bx_], [ay, my, by_], "-o", color=TRANSECT_C, lw=2, ms=5)
    ax.plot(mx, my, "o", color=TRANSECT_C, ms=8, mec="white", mew=1.5)
    if annotate:
        for (x, y), lab in [(pts["endpoint_a"], "A"), (pts["midpoint"], "midpoint"), (pts["endpoint_b"], "B")]:
            ax.annotate(lab, (x, y), xytext=(6, 6), textcoords="offset points", fontsize=10)
        ax.annotate("prescribed\ncentroid", (0, 0), xytext=(-60, -30), textcoords="offset points",
                    fontsize=9, color="dimgrey")
        ax.annotate(f"{MAX_MIDPOINT_SHIFT_M} m allowed shift", (0, -MAX_MIDPOINT_SHIFT_M), xytext=(0, -14),
                    textcoords="offset points", ha="center", fontsize=9, color="dimgrey")
    ax.set(xlim=(-55, 55), ylim=(-55, 55), aspect="equal")
    ax.grid(alpha=0.2)


geo = plots.dropna(subset=["midpoint_lat", "endpoint_a_lat", "endpoint_b_lat"]).sort_values("plot_name")

# 1. One plot, annotated, to read the small multiples below.
ex = geo.loc[geo["midpoint_shift_m"].idxmax()]
fig, ax = plt.subplots(figsize=(6, 6))
draw_plot(ax, ex, annotate=True)
ax.set(xlabel="east of centroid (m)", ylabel="north of centroid (m)",
       title=f"{ex['plot_name']}\nshift {ex['midpoint_shift_m']:.0f} m · A–mid {ex['a_to_mid_m']:.0f} m · "
             f"B–mid {ex['b_to_mid_m']:.0f} m · {ex['bearing_deviation_deg']:.0f}° off N–S")
ax.legend(handles=[plt.Line2D([], [], color=PRESCRIBED_C, lw=2, alpha=0.5, label="SOP: 50 m N–S at centroid"),
                   plt.Line2D([], [], color=TRANSECT_C, lw=2, marker="o", label="recorded A–midpoint–B"),
                   plt.Line2D([], [], color="black", ls=":", label="midpoint shift")],
          loc="upper right", fontsize=8)
plt.show()

# 2. All plots at the same scale.
ncol = 6
fig, axes = plt.subplots(int(np.ceil(len(geo) / ncol)), ncol, figsize=(2.6 * ncol, 2.8 * np.ceil(len(geo) / ncol)),
                         sharex=True, sharey=True)
for ax, (_, r) in zip(axes.flat, geo.iterrows()):
    draw_plot(ax, r)
    ax.set_title(f"{r['plot_name'].split('_')[-1]} · {r['midpoint_shift_m']:.0f} m · "
                 f"{r['bearing_deviation_deg']:.0f}°", fontsize=9)
for ax in axes.flat[len(geo):]:
    ax.set_visible(False)
fig.suptitle("All registered plots, ±55 m around the prescribed centroid (title: plot · shift · degrees off N–S)",
             y=1.0)
fig.tight_layout()
plt.show()

# %% [markdown]
# ### 2.2 Surveys and quadrats

# %% [markdown]
# This cell builds two clean tables from the raw survey export. It also measures how far the field data sits from the registered plot.
#
# **`surveys`: one row per survey submission.**
# - Renames the raw form fields to short column names: plot, replicate, recorder, device, start and end time, review state, and the GPS point taken when the survey was closed.
# - `team_size` counts the team member IDs, which the form stores as one space-separated string.
# - `duration_min` is the time from survey start to survey end.
# - `is_valid` is false only for submissions a reviewer rejected. Rejected surveys stay in the table but are excluded from the metrics.
# - `end_to_plot_m` is the distance from the survey's end GPS point to the plot's registered midpoint. A large value suggests the survey was closed away from the plot.
#
# **`quadrats`: one row per quadrat inside a survey.**
# - Each quadrat is linked to its survey through `PARENT_KEY`. It inherits the plot name, plot ID and `is_valid` flag from that survey.
# - It records the quadrat number, whether herbs or additional species were present, the selected species IDs, and the quadrat's own GPS point.
#
# **Distance checks for each quadrat.** All positions are first converted to metres around the plot midpoint.
# - `dist_to_midpoint_m` is the straight-line distance from the quadrat to the registered midpoint.
# - `dist_to_line_m` is the distance from the quadrat to the recorded transect between endpoint A and endpoint B. The code finds the closest point on that line segment and measures to it. Here `t` is how far along the segment that closest point lies, from 0 at A to 1 at B. Clipping `t` to that range means quadrats beyond either end are measured to the nearest endpoint.
#
# Quadrats should lie on the transect, so a large `dist_to_line_m` flags a quadrat recorded off the line. The last line prints the number of surveys, valid surveys, quadrats and registered plots.

# %%
# clean
surveys = pd.DataFrame({
    "survey_key": survey_raw["KEY"],
    "vegplot_id": survey_raw["plot_selection-selected_plot_uuid"],
    "plot_name": survey_raw["plot_selection-plot_name"],
    "replicate": survey_raw["survey_begin-replicate"],
    "recorder": survey_raw["field_team_specifics-recorder_label"],
    "team_size": survey_raw["field_team_specifics-selected_project_team_uuid_multi"].str.split().str.len(),
    "device": survey_raw["DeviceID"],
    "start": pd.to_datetime(survey_raw["survey_begin-start_time"], utc=True),
    "end": pd.to_datetime(survey_raw["survey_end-end_time"], utc=True),
    "review_state": survey_raw["ReviewState"].fillna("not reviewed"),
    "end_lat": survey_raw["survey_end-background_geopoint-Latitude"],
    "end_lon": survey_raw["survey_end-background_geopoint-Longitude"],
    "end_accuracy_m": survey_raw["survey_end-background_geopoint-Accuracy"],
})
surveys["date"] = surveys["start"].dt.date
surveys["duration_min"] = (surveys["end"] - surveys["start"]).dt.total_seconds() / 60
surveys["is_valid"] = surveys["review_state"] != "rejected"  # rejected submissions are excluded from metrics
surveys = surveys.merge(plots[["vegplot_id", "midpoint_lat", "midpoint_lon"]], on="vegplot_id", how="left")
surveys["end_to_plot_m"] = dist_m(surveys["end_lat"], surveys["end_lon"], surveys["midpoint_lat"], surveys["midpoint_lon"])

H = "herb_species-"
quadrats = pd.DataFrame({
    "quadrat_key": quadrat_raw["KEY"],
    "survey_key": quadrat_raw["PARENT_KEY"],
    "quadrat_number": quadrat_raw["quadrat_number"],
    "herbs_present": quadrat_raw["herbs_present"],
    "additional_species_present": quadrat_raw["additional_species_present"],
    "list_species_uuids": quadrat_raw[f"{H}selected_herb_species_uuids"],
    "lat": quadrat_raw["location_quadrat-Latitude"],
    "lon": quadrat_raw["location_quadrat-Longitude"],
    "accuracy_m": quadrat_raw["location_quadrat-Accuracy"],
}).merge(surveys[["survey_key", "plot_name", "vegplot_id", "is_valid"]], on="survey_key", how="left")

# Distance of each quadrat to the registered midpoint and to the A-B transect line.
q = quadrats.merge(plots[["vegplot_id", "endpoint_a_lat", "endpoint_a_lon", "midpoint_lat", "midpoint_lon",
                          "endpoint_b_lat", "endpoint_b_lon"]], on="vegplot_id", how="left")
ax_, ay_ = xy_m(q["endpoint_a_lat"], q["endpoint_a_lon"], q["midpoint_lat"], q["midpoint_lon"])
bx_, by_ = xy_m(q["endpoint_b_lat"], q["endpoint_b_lon"], q["midpoint_lat"], q["midpoint_lon"])
px_, py_ = xy_m(q["lat"], q["lon"], q["midpoint_lat"], q["midpoint_lon"])
t = (((px_ - ax_) * (bx_ - ax_) + (py_ - ay_) * (by_ - ay_)) / ((bx_ - ax_) ** 2 + (by_ - ay_) ** 2)).clip(0, 1)
quadrats["dist_to_midpoint_m"] = np.hypot(px_, py_)
quadrats["dist_to_line_m"] = np.hypot(px_ - (ax_ + t * (bx_ - ax_)), py_ - (ay_ + t * (by_ - ay_)))

print(f"{len(surveys)} surveys ({surveys['is_valid'].sum()} not rejected), {len(quadrats)} quadrats, "
      f"{len(plots)} registered plots")

# %%
surveys.head()

# %% [markdown]
# ### 2.3 Species records (one row per species per quadrat)
#
# Species reach the data in two ways:
#
# * **List species** are picked from the project species list. The quadrat stores space-separated UUIDs that
#   join to `species.csv`.
# * **Additional species** are either missing from the list (free-text canonical) or unknown (provisional
#   `herb_###` code). Each one is an entity in `species_extra.csv`. The later identifications in
#   `species_extra_ids.csv` give the name the species was identified as.
#
# The resolved name is the identification if there is one. Otherwise it is the provisional code, so an
# unidentified species still counts as one morphospecies.

# %%
# 1. Species ticked from the species list: one row per quadrat and species.
list_records = quadrats[["quadrat_key", "list_species_uuids"]].dropna().copy()
list_records["entity_id"] = list_records["list_species_uuids"].str.split()  # space-separated IDs -> list
list_records = list_records.explode("entity_id")  # one row per ID
list_records = list_records.merge(species[["__id", "label"]], left_on="entity_id", right_on="__id", how="left")
list_records["source"] = "species list"
list_records["recorded_name"] = list_records["label"]
list_records["resolved_name"] = list_records["label"]  # list species are already identified
list_records["provisional_code"] = None
list_records["id_note"] = None

# 2. Extra species created in the field, with their later identification (if any).
extra = species_extra.copy()
extra["provisional_code"] = "herb_" + extra["unknown_index"].astype(str).str.zfill(3)  # e.g. herb_007
extra = extra.merge(species_ids[["species_number", "species_name", "notes"]], left_on="provisional_code",
                    right_on="species_number", how="left")

# 3. Additional species recorded in a quadrat. New entries point to the entity they create,
#    reused entries to the entity they pick, so take whichever of the three fields is filled.
entity_id = addsp_raw["target_extra_name"]
entity_id = entity_id.fillna(addsp_raw["select_reuse_unknown"])
entity_id = entity_id.fillna(addsp_raw["select_reuse_missing"])
add_records = pd.DataFrame({
    "quadrat_key": addsp_raw["PARENT_KEY"],
    "record_key": addsp_raw["KEY"],
    "entity_id": entity_id,
})
extra_cols = ["__id", "label", "provisional_code", "species_name", "notes", "new_record_reason"]
add_records = add_records.merge(extra[extra_cols], left_on="entity_id", right_on="__id", how="left")

SOURCE_LABELS = {"missing_species": "additional (missing from list)", "unknown_species": "additional (unknown)"}
add_records["source"] = add_records["new_record_reason"].map(SOURCE_LABELS)
add_records["recorded_name"] = add_records["label"]
# Use the identified name. Fall back to the provisional code while the species is still unknown.
still_unknown = add_records["species_name"].isna() | (add_records["species_name"] == "Unknown")
add_records["resolved_name"] = np.where(still_unknown, add_records["provisional_code"], add_records["species_name"])
add_records["id_note"] = add_records["notes"]

# 4. Combine both sources into one table of species records.
cols = ["quadrat_key", "source", "entity_id", "provisional_code", "recorded_name", "resolved_name", "id_note"]
records = pd.concat([list_records[cols], add_records[cols + ["record_key"]]], ignore_index=True)
records["resolved_name"] = records["resolved_name"].str.strip()  # the only normalisation (see top)
records["is_unidentified"] = records["resolved_name"].str.match(r"^herb_\d{3}$", na=False)
records = records.merge(quadrats[["quadrat_key", "survey_key", "plot_name", "is_valid"]], on="quadrat_key")

# %%
records.head()

# %%

records.groupby("source").agg(records=("quadrat_key", "size"), names=("resolved_name", "nunique"))

# %% [markdown]
# ### 2.4 Taxonomic check of free-text names against GBIF
#
# Names typed in the field, or added during identification, are not checked against any taxonomy. The
# project species list carries GBIF taxon keys, so the GBIF backbone is the natural reference. I match each
# free-text name once with the GBIF species-match API and cache the answer, so the notebook also runs offline.

# %%


GBIF_CACHE = OUT / "gbif_name_matches.csv"
free_text = sorted(
    records.loc[(records["source"] != "species list") & ~records["is_unidentified"], "resolved_name"].dropna().unique()
)
cache = pd.read_csv(GBIF_CACHE) if GBIF_CACHE.exists() else pd.DataFrame(columns=["name"])
todo = [n for n in free_text if n not in set(cache["name"])]
rows = []
for name in todo:
    url = "https://api.gbif.org/v1/species/match?" + urllib.parse.urlencode({"name": name, "kingdom": "Plantae"})
    with urllib.request.urlopen(url, timeout=20) as r:
        m = json.load(r)
    rows.append({"name": name, "match_type": m.get("matchType"), "rank": m.get("rank"),
                 "status": m.get("status"), "gbif_canonical": m.get("canonicalName"),
                 "gbif_accepted": m.get("species"), "confidence": m.get("confidence")})
if rows:
    cache = pd.concat([cache, pd.DataFrame(rows)], ignore_index=True)
    cache.to_csv(GBIF_CACHE, index=False)
gbif = cache[cache["name"].isin(free_text)]
gbif["match_type"].value_counts()
