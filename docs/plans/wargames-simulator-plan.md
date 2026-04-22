# Wargames Simulator Plan

## Goal

Build a U.S. grid resilience simulator that supports scenario planning, dependency analysis, and impact estimation without compiling exact targeting-grade infrastructure locations.

## Safe Scope

We will model the grid using coarse public geography:

- generation assets aggregated to county, state, balancing-authority, or grid-region level
- transmission represented as high-voltage corridor segments or generalized line geometry
- substations represented as counts, classes, or regional summaries rather than exact coordinates

We will not store or publish exact substation coordinates in this repository.

## Phase 1: Data Foundation

Create a repeatable ingestion pipeline for three core layers:

1. Power generation
   - source: EIA Form 860 / EIA-860M
   - output: cleaned plant table and aggregated plant summary tables
2. Transmission
   - source: EIA Energy Atlas references HIFLD transmission line data
   - output: generalized corridor layer and state/county corridor summaries
3. Substations
   - source: public high-level references only
   - output: substation counts or regional density summaries, not exact points

## Phase 2: Normalized Schema

Standardize all infrastructure layers to shared fields:

- `asset_type`
- `source_name`
- `source_version`
- `source_date`
- `region_type`
- `region_id`
- `region_name`
- `latitude`
- `longitude`
- `geometry_precision`
- `capacity_mw`
- `voltage_kv`
- `fuel_type`
- `status`
- `owner_operator`

Notes:

- `latitude` and `longitude` should only be populated for assets that are appropriate to represent at point level under repo policy.
- `geometry_precision` should explicitly mark `state`, `county`, `ba_region`, `generalized_line`, or `point`.

## Phase 3: Simulation Model

Start simple and iterate:

1. Baseline topology
   - plants feed regions
   - regions connect through generalized transmission corridors
   - substations act as regional transfer and load-distribution nodes
2. Stress inputs
   - weather event by region
   - generator outage
   - corridor degradation
   - substation capacity reduction at regional level
3. Outputs
   - unmet demand by region
   - reserve margin change
   - cross-region dependency stress
   - critical-service exposure for hospitals, water, telecom, and fuel

## Recommended Repo Layout

- `data/raw/`
- `data/processed/`
- `data/public/`
- `docs/plans/`
- `docs/sources/`
- `schemas/`
- `scripts/`

## Immediate Build Order

1. Ingest EIA power plant data and create a cleaned plant table.
2. Add a coarse transmission corridor dataset and normalize voltage classes.
3. Define a regional substation summary format.
4. Build one map view that plots:
   - plant points where policy allows
   - generalized transmission corridors
   - substation density or count by region
5. Add one scenario runner for regional outages and load-transfer stress.

## What I Need Help With Later

- choosing the first geography level: county, state, balancing authority, or interconnection
- deciding whether the first simulator should be map-first or scenario-first
- confirming whether we want a browser app, notebook workflow, or static reports first
