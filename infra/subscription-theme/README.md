# Web theme for subscription-page 7.2.0

Serve `rovyn.css` and `rovyn.js` from the frontend assets directory. Load the stylesheet in the document head and the script with `defer`. They adapt the native installation steps, Happ import and QR dialog.

Serve `summary.css` as `/assets/rovyn-summary.css` and `summary.js` as `/assets/rovyn-summary.js`. Add the following line immediately after the existing `#sbpg` element in the upstream HTML template. The script must read the subscription data before the upstream React app consumes that element.

```html
<script src="/assets/rovyn-summary.js?v=1"></script>
```

The summary uses the panel's subscription status and expiry. For personal device links, it displays the shared account quota returned by the Rovyn API. Missing usage is shown as unknown. Keep the upstream frontend bundle and native download handlers in place.
