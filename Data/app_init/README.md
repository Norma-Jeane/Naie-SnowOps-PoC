# data/app_init

App initialization input area.

This directory is for fixed, read-only input data used when the app starts.
D3_app.py must not generate or overwrite files here during normal app execution.

Road master files for `road_selection_level` 0 to 3 are planned under:

- `data/app_init/roads/priority_roads_level0.geojson`
- `data/app_init/roads/priority_roads_level1.geojson`
- `data/app_init/roads/priority_roads_level2.geojson`
- `data/app_init/roads/priority_roads_level3.geojson`

Level policy:

- `road_selection_level 0`: no snow-removal target roads
- `road_selection_level 1`: highest-priority roads only
- `road_selection_level 2`: major roads
- `road_selection_level 3`: broad target set including residential roads
