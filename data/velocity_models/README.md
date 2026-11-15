# 1-D velocity models (`kim1983.csv`, `kim2011.csv`)

A *1-D velocity model* gives the speed of seismic waves as a function of depth only. These two models
are layered: inside each layer the speeds are constant. They are used in this tutorial (and in
PocketQuake) to compute travel times for earthquake location.

| column | meaning | units |
|---|---|---|
| `top_km` | depth of the top of the layer below the surface | km |
| `vp` | P-wave speed in the layer | km/s |
| `vs` | S-wave speed in the layer | km/s |

How to read a file: each layer reaches from its `top_km` down to the next row's `top_km`. The last row
continues to any depth (a *half-space*). Its P-wave speed is close to 8 km/s, typical of the uppermost
mantle, so its `top_km` is the model's Moho (crust-mantle boundary) depth.

| file | model | layers |
|---|---|---|
| `kim1983.csv` | Kim and Kim (1983) | 3 |
| `kim2011.csv` | Kim, Rhie and Kim (2011) | 4 |

Full citations are in `citations.yaml`. The values were checked against the original papers.
Load a model with `st.data.velocity_model("kim1983")`.

Prepared for the SGTL earthquake source tutorial by Minseong Seo (SGTL, Seoul National University).
