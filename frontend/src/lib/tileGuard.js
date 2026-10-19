/*
  Recognises OpenStreetMap's "Access blocked" tile.

  OSM's tile servers answer a blocked request (no Referer, no attribution, or "App is not following
  the tile usage policy") with an ordinary HTTP 200 PNG. Leaflet therefore draws it as a map tile
  and no tileerror fires. Seen in Chrome 155 on 2026-10-17 for the standalone ML maps opened from a
  file. Every variant carries a pure yellow and black hazard stripe down the left edge, at columns
  8-19 and rows 8-239 of a 256 px tile. Map tiles never have this stripe.

  Reading pixels needs the tile to be loaded with CORS (crossOrigin="anonymous"). OSM allows this.
  For a provider without CORS, nothing can be read and the check answers "not blocked".
*/

export const BLOCK_BAND = { x: 8, y: 8, width: 12, height: 232 }; // in a 256 px tile

/** True if RGBA pixels from the band look like the hazard stripe (about half yellow, half black). */
export function isOsmBlockBand(rgba) {
  let yellow = 0;
  let black = 0;
  for (let i = 0; i < rgba.length; i += 4) {
    const [r, g, b, a] = [rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]];
    if (r > 230 && g > 230 && b < 40) yellow += 1;
    else if (r < 30 && g < 30 && b < 30 && a > 200) black += 1;
  }
  const n = rgba.length / 4;
  return n > 0 && yellow / n > 0.3 && black / n > 0.3;
}

let canvas = null;

/** True if a loaded tile <img> is OSM's "Access blocked" image. */
export function isOsmBlockTile(img) {
  const w = img?.naturalWidth || 0;
  if (w < 128 || (img.naturalHeight || 0) < 128 || typeof document === 'undefined') return false;
  const k = w / 256;
  const [x, y, bw, bh] = [BLOCK_BAND.x, BLOCK_BAND.y, BLOCK_BAND.width, BLOCK_BAND.height].map((v) => Math.round(v * k));
  canvas = canvas || document.createElement('canvas');
  canvas.width = bw;
  canvas.height = bh;
  try {
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.clearRect(0, 0, bw, bh);
    ctx.drawImage(img, x, y, bw, bh, 0, 0, bw, bh);
    return isOsmBlockBand(ctx.getImageData(0, 0, bw, bh).data);
  } catch {
    return false; // tainted canvas (no CORS): cannot tell
  }
}
