# Offline map geometry

`korea_coast.bna` contains public GSHHG low-resolution level-1 coastline geometry,
cropped to 123–133° E and 31–41° N with GMT 6.5.0. It contains no earthquakes,
station measurements, waveforms or laboratory results. The lines give geographic
context; they are not active-fault traces or administrative boundaries.

Source: [GSHHG](https://www.soest.hawaii.edu/pwessel/gshhg/),
Wessel, P. and Smith, W. H. F. (1996), *A global, self-consistent, hierarchical,
high-resolution shoreline database*, Journal of Geophysical Research 101(B4),
8741–8743, [doi:10.1029/96JB00104](https://doi.org/10.1029/96JB00104).
GSHHG is distributed under the GNU Lesser General Public License; see the
[upstream distribution and license](https://github.com/GenericMappingTools/gshhg-gmt).
This source geometry retains its upstream license.

The instructor repository's `mentor/scripts/make_seiscomp_map.py` records the
export procedure. The offline session copies the geometry into its own
SeisComP configuration; no global map installation is required.
