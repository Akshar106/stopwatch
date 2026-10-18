// CloudFront Function (cloudfront-js-2.0), viewer-request, default behavior only.
//
// The SPA uses client-side routing (/s/mbta/64, /r/mbta/1, /commutes, /about/methodology, ...), but
// S3 only knows real objects. Any path whose last segment has no file extension, and that is not
// under /data/, /api/ or /assets/, is a client-side route: serve /index.html for it. Real files
// (/sw.js, /assets/app-3f9a.js, /favicon.ico) pass through untouched, so a missing file is still
// an honest 404 rather than an HTML page.
//
// Runs before the cache lookup, so every SPA route shares the single cached /index.html.
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.startsWith('/data/') || uri.startsWith('/api/') || uri.startsWith('/assets/')) {
    return request;
  }

  var lastSegment = uri.substring(uri.lastIndexOf('/') + 1);
  if (lastSegment.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
