Sourdough hero photo
====================

File: `frontend/src/assets/bread-hero.jpg`
SHA-256: `e3abea60dae5a00affaf60c691a2e5ebc9f77edc02923a81b7d9177e311829d5`

Source (independently verifiable):
- File page: https://commons.wikimedia.org/wiki/File:Homemade_Sourdough_Boule.jpg
- Download URL used: https://upload.wikimedia.org/wikipedia/commons/thumb/5/5f/Homemade_Sourdough_Boule.jpg/1920px-Homemade_Sourdough_Boule.jpg
- Author: Wikimedia Commons user Alyinthearchives ("Own work")
- Description on the file page: a homemade sourdough boule on parchment paper in a cast-iron dutch oven, lid off.
- Date: 2024-06-22.
- License: CC0 1.0 Universal Public Domain Dedication,
  https://creativecommons.org/publicdomain/zero/1.0/deed.en
  The file page reports "Attribution not required". The photo is credited anyway,
  and the interface labels it as an illustration rather than the seller's product.

Why this file: it is plain sourdough (not a branded or third-party bakery product),
the license is a public-domain dedication that can be checked on the file page, and
the warm tone fits the approved bright and warm direction.

Not used: Pinterest reference images, Astro product photos, or any image whose license
could not be verified. The visible caption in the catalog says the photo is an
illustration, not the actual product. This is not a claim that the business has
photographed its own bread.

Plus Jakarta Sans variable font
===============================

Package: `@fontsource-variable/plus-jakarta-sans` version `5.3.0`, pinned exactly in
`frontend/package.json` and `frontend/package-lock.json`.
File used: `files/plus-jakarta-sans-latin-wght-normal.woff2`
SHA-256: `153fc85b70298beeb1d61a5f723331649e7f23bb77302a66e61cb3e2fbdb5e79`
Size: 27,348 bytes.

Source (independently verifiable):
- Package: https://www.npmjs.com/package/@fontsource-variable/plus-jakarta-sans/v/5.3.0
- Package repository: https://github.com/fontsource/font-files/tree/main/fonts/variable/plus-jakarta-sans
- Font project: Plus Jakarta Sans Project Authors, https://github.com/tokotype/PlusJakartaSans
- Font source/version: Google Fonts, version `v12` as recorded in the package `metadata.json`.
- License: SIL Open Font License 1.1 (OFL-1.1), https://openfontlicense.org
  Copyright 2020 The Plus Jakarta Sans Project Authors. The full OFL text ships as
  `LICENSE` inside the installed package. The build also copies that unmodified
  copyright/license text to `dist/plus-jakarta-sans-OFL.txt`, served alongside the
  redistributed font at `/plus-jakarta-sans-OFL.txt`.

Why this file: the weight axis covers 200-800, so the existing 400/600/700 hierarchy
needs one file per script subset. Only the Latin subset is declared and bundled; the
app never requests Google Fonts or another external font host at runtime. Vite copies
and fingerprints the WOFF2 into `frontend/dist/assets/` as a self-hosted asset.
