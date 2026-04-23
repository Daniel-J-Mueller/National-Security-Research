# Private People Data

This category can hold temporary or cloned source material used to build public people outputs.

Current workflow:

- Census source files live in `data/raw/people/census/`
- The builder can read `data/private/_tmp_us_town_halls/combined_data/combined_town_halls.csv`
- A dedicated `data/private/people/town_halls/combined_town_halls.csv` source can be added later if we want to persist a local copy here
- The richer private output now lives at `data/private/people/municipal_population_town_halls_2024_private.csv`
