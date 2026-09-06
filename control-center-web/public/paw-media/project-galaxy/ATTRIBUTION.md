# Project galaxy surface data

These images are used on three-dimensional sphere geometry. They are stored
locally, loaded only for visible surface types, and capped at 2048 × 1024.
They do not turn the navigation view into a calibrated astronomical atlas.

- `moon-color-2k.jpg`: NASA Scientific Visualization Studio, Ernie Wright,
  LROC WAC color mosaic, 2025 revision. Unmodified JPEG from the
  [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/), downloaded 2026-09-06.
  SHA-256: `f7130a1822681fa7512d7dcfd40db8c10b9ba4f06777910348698260ed7a2170`.
- `moon-height-1k.jpg`: NASA Scientific Visualization Studio, LRO / LOLA
  elevation data, unmodified 8-bit JPEG preview from the same kit. Used as a
  bounded bump / displacement map, not as scientific elevation output.
  SHA-256: `6d93f887e7d8bedfe35ab89ba785e5e3ca12381bd092a5e6abe2c707dda8bb98`.
- `earth-clouds-2k.jpg`: [Solar System Scope / INOVE](https://www.solarsystemscope.com/textures/),
  `2k_earth_clouds.jpg`, unmodified, downloaded 2026-09-06. Distributed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
  SHA-256: `fffd7f68d41b37274822150e54a6ef605af1d3ec35624d9f628c3b896bfa42ed`.
- `mars-viking.jpg`: NASA / Jet Propulsion Laboratory & Caltech; Viking images
  processed at USGS. Unmodified JPEG from [NASA's Mars image texture](https://science.nasa.gov/3d-resources/mars/),
  downloaded 2026-09-06. Source: `https://assets.science.nasa.gov/content/dam/science/cds/3d/resources/image/mars/Mars.jpg`.
  SHA-256: `12ec6bf02ebd42a246edc778cb2ce8c595b4d9f0892badf0bfff8abb2303c780`.

The Earth, Jupiter, Saturn and Mercury color maps are the existing
locally bundled Solar System Scope maps in `../starfield/`; their source,
license and prior resampling are recorded in [that attribution](../starfield/ATTRIBUTION.md).
The old Starfield renderer is not used by the project galaxy.
