from pathlib import Path
import pandas as pd
import gc

# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIR = Path("./data/csew")
OUTPUT_DIR = Path("./data/csew/merged")

CSEW_EARLIEST = 11
CSEW_LATEST = 24

# Separate bolt-on switches.
# NVF bolt-ons are respondent-level and use rowlabel.
# VF bolt-ons are summary/derived files and use match.
GENERATE_NVF_BOLTON = True
GENERATE_VF_BOLTON = False

INCLUDE_10_15 = False

# If True, existing output files with the same names are deleted first.
OVERWRITE_OUTPUTS = True

# ============================================================
# WAVE MAP
# ============================================================

WAVES = {
    11: "2011-12",
    12: "2012-13",
    13: "2013-14",
    14: "2014-15",
    15: "2015-16",
    16: "2016-17",
    17: "2017-18",
    18: "2018-19",
    19: "2019-20",
    22: "2022-23",
    23: "2023-24",
    24: "2024-25",
}


# ============================================================
# FUNCTION: build_wave_prefix
# Builds the filename prefix used by the CSEW .tab files.
#
# Example:
#   11 -> csew_apr11mar12
# ============================================================

def build_wave_prefix(wave_code):
    end = str(wave_code + 1).zfill(2)
    return f"csew_apr{wave_code:02d}mar{end}"


# ============================================================
# FUNCTION: output_prefix
# Creates the output filename prefix using the selected first wave.
#
# Example:
#   CSEW_EARLIEST = 11 -> Post2011
#   CSEW_EARLIEST = 13 -> Post2013
# ============================================================

def output_prefix():
    return f"Post{2000 + CSEW_EARLIEST}"


# ============================================================
# FUNCTION: load_tab_file
# Loads one .tab file using a memory-safer pandas configuration.
#
# All columns are read as strings to avoid pandas type-inference spikes.
# ============================================================

def load_tab_file(path):
    print("-" * 60, flush=True)
    print(f"LOADING FILE:\n{path}", flush=True)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    df = pd.read_csv(
        path,
        sep="\t",
        dtype=str,
        low_memory=True,
    )

    print(f"LOADED: {df.shape[0]:,} rows x {df.shape[1]:,} cols", flush=True)
    return df


# ============================================================
# FUNCTION: create_global_ids
# Creates globally unique IDs by prefixing original identifiers with wave.
#
# Adds:
#   global_person_id
#   global_household_id
#   global_incident_id for victim-form files
# ============================================================

def create_global_ids(df, wave_code, vf=False):
    print(f"CREATING GLOBAL IDS FOR WAVE {wave_code}", flush=True)

    wave_str = f"20{wave_code:02d}"

    if "rowlabel" in df.columns:
        df["global_person_id"] = wave_str + "_" + df["rowlabel"].astype(str).str.strip()

    if "serial" in df.columns:
        df["global_household_id"] = wave_str + "_" + df["serial"].astype(str).str.strip()

    if vf and "rowlabel" in df.columns:
        incident_col = None

        for candidate in ["vno", "incser", "victimform", "vfnum", "offence"]:
            if candidate in df.columns:
                incident_col = candidate
                break

        if incident_col is not None:
            df["global_incident_id"] = (
                wave_str
                + "_"
                + df["rowlabel"].astype(str).str.strip()
                + "_"
                + df[incident_col].astype(str).str.strip()
            )
        else:
            # Fallback: row number within person.
            df["_incident_sequence"] = df.groupby("rowlabel").cumcount() + 1
            df["global_incident_id"] = (
                wave_str
                + "_"
                + df["rowlabel"].astype(str).str.strip()
                + "_"
                + df["_incident_sequence"].astype(str)
            )

    return df


# ============================================================
# FUNCTION: add_standard_variables
# Adds variables identifying the survey wave and post-2001 status.
# ============================================================

def add_standard_variables(df, wave_code):
    print(f"ADDING STANDARD VARIABLES FOR WAVE {wave_code}", flush=True)

    df["wave"] = 2000 + wave_code
    df["PREPOST2001"] = 1

    return df


# ============================================================
# FUNCTION: check_uniqueness
# Checks whether a column uniquely identifies rows.
# ============================================================

def check_uniqueness(df, col):
    if col not in df.columns:
        print(f"WARNING: {col} not found", flush=True)
        return False

    dups = df[col].astype(str).str.strip().duplicated().sum()

    if dups == 0:
        print(f"UNIQUE CHECK PASSED: {col}", flush=True)
        return True

    print(f"WARNING: {dups:,} duplicate values in {col}", flush=True)
    return False


# ============================================================
# FUNCTION: memory_safe_update_merge
# Memory-safe replacement for a wide pandas merge.
#
# This avoids constructing a large temporary dataframe with duplicate
# suffix columns.
#
# IMPORTANT:
#   This version does NOT overwrite existing main-file variables.
#   If a bolt-on column already exists in the main file, it is added as:
#       variable_bolton
#
#   If a bolt-on column is genuinely new, it is added with its original name.
#
# Adds:
#   indicator_name:
#       1 = main only
#       3 = matched in main and bolt-on
# ============================================================

def memory_safe_update_merge(main_df, using_df, key, indicator_name):
    print("-" * 60, flush=True)
    print("STARTING MEMORY-SAFE UPDATE MERGE", flush=True)
    print(f"USING MERGE KEY: {key}", flush=True)

    if key not in main_df.columns:
        raise KeyError(f"Merge key {key!r} is missing from main file")

    if key not in using_df.columns:
        raise KeyError(f"Merge key {key!r} is missing from bolt-on file")

    main_df[key] = main_df[key].astype(str).str.strip()
    using_df[key] = using_df[key].astype(str).str.strip()

    if not check_uniqueness(main_df, key):
        raise ValueError(f"Main file has duplicate {key}; cannot safely 1:1 merge")

    if not check_uniqueness(using_df, key):
        raise ValueError(f"Bolt-on file has duplicate {key}; cannot safely 1:1 merge")

    print("SETTING INDEXES", flush=True)

    main = main_df.set_index(key, drop=False)
    using = using_df.set_index(key, drop=False)

    matched_mask = main.index.isin(using.index)
    main[indicator_name] = 1
    main.loc[matched_mask, indicator_name] = 3

    using_cols = [c for c in using.columns if c != key]

    overlapping_cols = [c for c in using_cols if c in main.columns]
    new_cols = [c for c in using_cols if c not in main.columns]

    print(f"BOLT-ON COLUMNS TOTAL: {len(using_cols):,}", flush=True)
    print(f"  OVERLAPPING COLUMNS TO ADD WITH _bolton SUFFIX: {len(overlapping_cols):,}", flush=True)
    print(f"  NEW COLUMNS TO ADD WITH ORIGINAL NAMES: {len(new_cols):,}", flush=True)

    print("PREPARING BOLT-ON COLUMNS WITHOUT OVERWRITING MAIN DATA", flush=True)

    new_data = {}

    # If the bolt-on variable does not already exist in the main file,
    # add it using its original name.
    for i, col in enumerate(new_cols, start=1):
        if i % 50 == 0:
            print(f"  prepared {i:,}/{len(new_cols):,} new columns", flush=True)
        new_data[col] = using[col].reindex(main.index)

    # If the bolt-on variable already exists in the main file,
    # keep the original main-file variable unchanged and add the
    # bolt-on version with a _bolton suffix.
    for i, col in enumerate(overlapping_cols, start=1):
        if i % 50 == 0:
            print(f"  prepared {i:,}/{len(overlapping_cols):,} overlapping columns with suffix", flush=True)

        suffixed_name = f"{col}_bolton"

        # Avoid accidental name collisions if a _bolton variable already exists.
        if suffixed_name in main.columns or suffixed_name in new_data:
            suffix_counter = 2
            candidate = f"{suffixed_name}{suffix_counter}"
            while candidate in main.columns or candidate in new_data:
                suffix_counter += 1
                candidate = f"{suffixed_name}{suffix_counter}"
            suffixed_name = candidate

        new_data[suffixed_name] = using[col].reindex(main.index)

    if new_data:
        main = pd.concat([main, pd.DataFrame(new_data, index=main.index)], axis=1)

    out = main.reset_index(drop=True).copy()

    print(f"MEMORY-SAFE MERGE COMPLETE: {out.shape[0]:,} rows x {out.shape[1]:,} cols", flush=True)

    del main
    del using
    gc.collect()

    return out


# ============================================================
# FUNCTION: load_wave_file
# Loads one wave file, then adds global IDs and standard variables.
# ============================================================

def load_wave_file(wave_code, kind="nvf", adolescent=False):
    wave_folder = WAVES[wave_code]
    prefix = build_wave_prefix(wave_code)

    if adolescent:
        filename = f"{prefix}_10-15_{kind}.tab"
    else:
        filename = f"{prefix}_{kind}.tab"

    path = DATA_DIR / wave_folder / "tab" / filename

    print("=" * 60, flush=True)
    print(f"PROCESSING WAVE {wave_code}", flush=True)
    print(f"TYPE: {kind}", flush=True)

    df = load_tab_file(path)
    df = create_global_ids(df, wave_code, vf=(kind == "vf"))
    df = add_standard_variables(df, wave_code)

    print(f"FINAL SHAPE AFTER ID/STANDARD VARIABLES: {df.shape}", flush=True)
    return df


# ============================================================
# FUNCTION: should_generate_bolton
# Decides whether bolt-on output should be generated for a file type.
#
# NVF and VF have separate True/False switches.
# ============================================================

def should_generate_bolton(kind):
    if kind == "nvf":
        return GENERATE_NVF_BOLTON

    if kind == "vf":
        return GENERATE_VF_BOLTON

    raise ValueError(f"Unknown file kind: {kind}")


# ============================================================
# FUNCTION: bolton_merge_key
# Returns the correct merge key for bolt-on files.
#
# NVF bolt-on:
#   key = rowlabel
#
# VF bolt-on:
#   key = match
# ============================================================

def bolton_merge_key(kind):
    if kind == "nvf":
        return "rowlabel"

    if kind == "vf":
        return "match"

    raise ValueError(f"Unknown file kind: {kind}")


# ============================================================
# FUNCTION: merge_wave_bolton_if_available
# Loads and merges the bolt-on file for waves where it exists.
#
# Currently implemented for 2011-12:
#   csew_apr11mar12_nvf_bolt-on.tab
#   csew_apr11mar12_vf_bolt-on.tab
# ============================================================

def merge_wave_bolton_if_available(df, wave_code, kind="nvf"):
    if not should_generate_bolton(kind):
        print(f"{kind.upper()} BOLT-ON DISABLED", flush=True)
        return df

    if wave_code != 11:
        print(f"NO BOLT-ON FOR WAVE {wave_code}", flush=True)
        return df

    print(f"LOADING BOLT-ON FOR WAVE {wave_code}, TYPE {kind}", flush=True)

    prefix = build_wave_prefix(wave_code)
    bolt_name = f"{prefix}_{kind}_bolt-on.tab"
    bolt_path = DATA_DIR / WAVES[wave_code] / "tab" / bolt_name

    bolt = load_tab_file(bolt_path)

    key = bolton_merge_key(kind)
    indicator_name = "bolton" if kind == "nvf" else "boltonVF"

    merged = memory_safe_update_merge(
        df,
        bolt,
        key=key,
        indicator_name=indicator_name,
    )

    del bolt
    gc.collect()

    return merged


# ============================================================
# FUNCTION: prepare_output_file
# Deletes an existing output file if OVERWRITE_OUTPUTS is True.
# ============================================================

def prepare_output_file(path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if path.exists() and OVERWRITE_OUTPUTS:
        print(f"REMOVING EXISTING OUTPUT FILE:\n{path}", flush=True)
        path.unlink()


# ============================================================
# FUNCTION: append_wave_to_output
# Writes one processed wave directly to the final output file.
#
# This keeps memory low because waves are not stored in a list.
# ============================================================

def append_wave_to_output(df, output_path, write_header):
    print("-" * 60, flush=True)
    print(f"WRITING WAVE TO OUTPUT:\n{output_path}", flush=True)
    print(f"WRITE HEADER: {write_header}", flush=True)
    print(f"ROWS/COLS BEING WRITTEN: {df.shape[0]:,} x {df.shape[1]:,}", flush=True)

    df.to_csv(
        output_path,
        sep="\t",
        index=False,
        mode="w" if write_header else "a",
        header=write_header,
    )

    print("WAVE WRITTEN TO DISK", flush=True)




# ============================================================
# FUNCTION: selected_wave_codes
# Returns selected wave codes that exist in the WAVES map.
# ============================================================

def selected_wave_codes():
    return [
        wave_code
        for wave_code in range(CSEW_EARLIEST, CSEW_LATEST + 1)
        if wave_code in WAVES
    ]


# ============================================================
# FUNCTION: get_columns_for_wave
# Loads one fully processed wave and returns its columns.
#
# Used during the first pass to build a harmonised schema.
# ============================================================

def get_columns_for_wave(wave_code, kind):
    df = load_wave_file(wave_code, kind=kind)
    df = merge_wave_bolton_if_available(df, wave_code, kind=kind)

    cols = list(df.columns)

    del df
    gc.collect()

    return cols


# ============================================================
# FUNCTION: build_harmonised_schema
# First pass across selected waves.
#
# Builds one complete column list for the selected time window.
# Column order is stable: columns appear in the order first found.
# ============================================================

def build_harmonised_schema(kind):
    print("#" * 60, flush=True)
    print(f"BUILDING HARMONISED COLUMN SCHEMA FOR {kind.upper()}", flush=True)

    all_cols = []
    seen = set()

    for wave_code in selected_wave_codes():
        print("=" * 60, flush=True)
        print(f"SCANNING COLUMNS FOR {kind.upper()} WAVE {wave_code}", flush=True)

        wave_cols = get_columns_for_wave(wave_code, kind)

        for col in wave_cols:
            if col not in seen:
                all_cols.append(col)
                seen.add(col)

        print(f"TOTAL SCHEMA COLUMNS SO FAR: {len(all_cols):,}", flush=True)

    print("#" * 60, flush=True)
    print(f"FINAL HARMONISED SCHEMA FOR {kind.upper()}: {len(all_cols):,} COLUMNS", flush=True)

    return all_cols


# ============================================================
# FUNCTION: harmonise_columns
# Aligns a processed wave to the global schema before writing.
#
# Adds missing columns as NA and reorders columns exactly.
# This prevents malformed appended .tab files where later waves have
# more/fewer columns than the header row.
# ============================================================

def harmonise_columns(df, schema_cols):
    print(
        f"SHAPE BEFORE HARMONISATION: {df.shape[0]:,} rows x {df.shape[1]:,} cols",
        flush=True
    )

    # Add all missing columns at once and reorder columns
    df = df.reindex(columns=schema_cols)

    print(
        f"SHAPE AFTER HARMONISATION: {df.shape[0]:,} rows x {df.shape[1]:,} cols",
        flush=True
    )

    return df


# ============================================================
# FUNCTION: run_streaming_pipeline
# Runs a streaming pipeline for either NVF or VF.
#
# Steps per wave:
#   1. load one wave
#   2. add IDs
#   3. merge bolt-on if enabled and available
#   4. write wave directly to output
#   5. delete the wave from memory
# ============================================================

def run_streaming_pipeline(kind):
    print("#" * 60, flush=True)
    print(f"STARTING HARMONISED STREAMING {kind.upper()} PIPELINE", flush=True)

    output_name = f"{output_prefix()}_{kind}.tab"
    output_path = OUTPUT_DIR / output_name

    prepare_output_file(output_path)

    # First pass: build one complete schema across all selected waves.
    # This prevents later waves from appending rows with a different
    # number/order of columns than the header.
    schema_cols = build_harmonised_schema(kind)

    wrote_any = False
    total_rows = 0

    # Second pass: process each wave, align it to the schema, then append.
    for wave_code in selected_wave_codes():
        print("=" * 60, flush=True)
        print(f"STARTING {kind.upper()} WAVE {wave_code}", flush=True)

        df = load_wave_file(wave_code, kind=kind)
        df = merge_wave_bolton_if_available(df, wave_code, kind=kind)

        print(f"SHAPE BEFORE HARMONISATION: {df.shape[0]:,} rows x {df.shape[1]:,} cols", flush=True)
        df = harmonise_columns(df, schema_cols)
        print(f"SHAPE AFTER HARMONISATION: {df.shape[0]:,} rows x {df.shape[1]:,} cols", flush=True)

        append_wave_to_output(
            df=df,
            output_path=output_path,
            write_header=not wrote_any,
        )

        total_rows += len(df)
        wrote_any = True

        print(f"COMPLETED {kind.upper()} WAVE {wave_code}", flush=True)
        print(f"TOTAL ROWS WRITTEN SO FAR FOR {kind.upper()}: {total_rows:,}", flush=True)

        print("DELETING WAVE DATAFRAME FROM MEMORY", flush=True)
        del df
        gc.collect()

    print("#" * 60, flush=True)
    print(f"HARMONISED STREAMING {kind.upper()} PIPELINE COMPLETE", flush=True)
    print(f"FINAL OUTPUT:\n{output_path}", flush=True)
    print(f"TOTAL ROWS WRITTEN: {total_rows:,}", flush=True)


# ============================================================
# FUNCTION: run_nvf_pipeline
# Runs the streaming NVF pipeline.
# ============================================================

def run_nvf_pipeline():
    run_streaming_pipeline("nvf")


# ============================================================
# FUNCTION: run_vf_pipeline
# Runs the streaming VF pipeline.
# ============================================================

def run_vf_pipeline():
    run_streaming_pipeline("vf")


# ============================================================
# FUNCTION: run
# Master pipeline.
#
# Runs:
#   - streaming NVF pipeline
#   - streaming VF pipeline
# ============================================================

def run():
    print("#" * 60, flush=True)
    print("CSEW/BCS STREAMING MERGER STARTED", flush=True)
    print(f"OUTPUT PREFIX: {output_prefix()}", flush=True)
    print(f"GENERATE_NVF_BOLTON: {GENERATE_NVF_BOLTON}", flush=True)
    print(f"GENERATE_VF_BOLTON: {GENERATE_VF_BOLTON}", flush=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_nvf_pipeline()
    run_vf_pipeline()

    print("#" * 60, flush=True)
    print("ALL STREAMING PROCESSING COMPLETE", flush=True)


if __name__ == "__main__":
    run()
