# Electric Grid Source Log

## Official Sources

### Power Plants

- U.S. Energy Information Administration, Form EIA-860 detailed data
  - URL: https://www.eia.gov/electricity/data/eia860/
  - Verified: April 21, 2026
  - Use: plant-level generation assets and attributes
  - Notes: includes plant-level information; handle geographic precision carefully in this repo

- U.S. Energy Information Administration, Preliminary Monthly Electric Generator Inventory (EIA-860M)
  - URL: https://www.eia.gov/electricity/data/eia860m/index.php
  - Verified: April 21, 2026
  - Use: recent generator additions, retirements, and status updates
  - Notes: monthly and more current than annual EIA-860, but preliminary

### Transmission

- U.S. Energy Information Administration FAQ on plant and transmission locations
  - URL: https://www.eia.gov/tools/faqs/faq.php?id=567&t=1
  - Verified: April 21, 2026
  - Use: confirms public availability and provenance of power plant and transmission mapping data
  - Notes: says transmission line data in the Energy Atlas is sourced from HIFLD rather than EIA

- U.S. Energy Information Administration, U.S. Energy Atlas / Maps
  - URL: https://www.eia.gov/maps/
  - Verified: April 21, 2026
  - Use: reference entry point for electric transmission mapping layers

### State and Regional Summaries

- U.S. Energy Information Administration, State Electricity Profiles
  - URL: https://www.eia.gov/electricity/state/unitedstates/
  - Verified: April 21, 2026
  - Use: state-level capacity, generation, and context for resilience analysis
  - Notes: useful for cross-checking aggregates built from plant-level data

## Constraints and Handling Notes

- EIA states that it does not publish the location of electric substations.
- This repository's README limits us to high-level resilience research and explicitly warns against compiling precise location or route-trace data for sensitive infrastructure.
- Because of those two constraints, the first dataset build should favor county, state, balancing-authority, or generalized-corridor outputs over exact substation mapping.
