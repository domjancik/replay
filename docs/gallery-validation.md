# Gallery and hosted USB checkpoint

The local gallery expands a selected notebook inline after its grid row. Twelve page slots fit in the drawer before internal scrolling (six, four or three columns at responsive breakpoints). Open notebook hides the other notebook cards; All notebooks returns to the inline gallery. Page selection preserves internal scroll. Thumbnail slots are observed against the viewport, including clipping by the inline page scroller. Only visible notebook covers and page slots join the sequential authenticated static-preview queue; offscreen pending work is removed, while already-submitted renders finish and remain cached. Completed replay images are reused when available. Cloud cards fetch available previews when visible, one at a time, without importing ink. They can wait behind an active replay. No device writes are involved.

Validation: Node regression coverage for inline placement, open/return/collapse and scroll retention; actual browser checks on the 21-page birthday notebook, page 18 selection, pages-only mode and a 390-pixel viewport with no horizontal overflow. Browser console had no errors. The local web suite passed 60 tests with loopback access.

## Hosted USB experiment

A code-only diagnostic is deployed at https://replay-usb-probe.vercel.app/ . It reads only the fixed tablet documents endpoint, uses omitted credentials and a ten-second timeout, and does not upload or persist tablet content. No notebook artwork was deployed.

The HTTPS in-app-browser request timed out. A separate bounded, read-only HTTP probe to the connected tablet returned HTTP 200 but no Access-Control-Allow-Origin header when sent the diagnostic origin. The timeout alone does not distinguish local-network permission from CORS or browser transport behavior. The header result independently shows that a normal cross-origin fetch cannot read this response. Hosted direct USB import is therefore not validated/supported by this experiment; the existing local backend route remains available. Only the diagnostic, not the Python-backed gallery app, was deployed.
