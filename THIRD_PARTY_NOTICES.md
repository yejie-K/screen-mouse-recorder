# Third-Party Notices

This repository contains integration code for third-party software but does not
vendor FFmpeg binaries, OCR runtime wheels, model weights, or Tesseract language
data in the source snapshot.

| Component | Usage | Distribution note |
|---|---|---|
| Python | Runtime | Subject to the Python Software Foundation License |
| Pillow | Image processing | Subject to Pillow's upstream license |
| openpyxl | XLSX generation | MIT License |
| RapidOCR / ONNX Runtime | Optional local OCR | Install separately and review the licenses shipped with the selected package versions |
| FFmpeg | External video process | Not bundled; the applicable LGPL/GPL obligations depend on the exact FFmpeg build selected by the user |
| Tk / Tcl | Desktop UI | Supplied by the user's Python distribution and subject to its upstream license |
| React / React DOM | Manual review web UI | MIT License |
| XYFlow | Manual review graph and canvas UI | MIT License |
| Lucide | UI icons | ISC License |
| Vite / React plugin | Frontend build tooling | MIT License |
| TypeScript | Frontend build tooling | Apache License 2.0 |

Before creating a binary distribution, regenerate a dependency inventory from
the actual build environment and include the exact license texts required by
those versions. The checked-in `tools/manual_frame_review_web/dist/` bundle
contains compiled frontend dependencies listed above. Do not copy an arbitrary
FFmpeg build or OCR model into a release without checking its redistribution
terms.
