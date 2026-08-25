# 星空 planetary texture attribution

The equirectangular surface maps in this directory are downscaled (2k → 1k,
moon → 512) copies of the texture set shipped by the MIT-licensed reference
project [q-jade/solar-system](https://github.com/q-jade/solar-system)
(`src/textures/`). That project sources them from
[Solar System Scope](https://www.solarsystemscope.com/textures/), which
distributes its planetary texture pack under the
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/)
license (imagery based on NASA elevation and imagery data).

Modifications made here:

- every 2048×1024 map resampled to 1024×512 (Lanczos), moon to 512×256, and
  the Saturn ring alpha strip to 1024×64 — the starfield's performance budget
  prefers 1k maps over shipping 2k originals;
- `uranus-1k.jpg` has a contrast boost (~1.6×) baked in, porting the runtime
  contrast stretch the reference project applies, so no per-boot canvas work
  is needed.

| File | Body | Source file |
| --- | --- | --- |
| `sun-1k.jpg` | Sun | `2k_sun.jpg` |
| `mercury-1k.jpg` | Mercury | `2k_mercury.jpg` |
| `venus-1k.jpg` | Venus | `2k_venus_surface.jpg` |
| `earth-1k.jpg` | Earth | `2k_earth_daymap.jpg` |
| `mars-1k.jpg` | Mars | `2k_mars.jpg` |
| `jupiter-1k.jpg` | Jupiter | `2k_jupiter.jpg` |
| `saturn-1k.jpg` | Saturn | `2k_saturn.jpg` |
| `saturn-ring-1k.png` | Saturn rings | `2k_saturn_ring_alpha.png` |
| `uranus-1k.jpg` | Uranus | `2k_uranus.jpg` |
| `neptune-1k.jpg` | Neptune | `2k_neptune.jpg` |
| `moon-512.jpg` | Moon | `2k_moon.jpg` |

The MIT license text of the reference project:

```text
MIT License

Copyright (c) 2026 q-jade

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
