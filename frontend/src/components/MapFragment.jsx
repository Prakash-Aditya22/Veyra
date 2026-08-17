import './MapFragment.css';

/*
  Inline map typography.

  A small rounded crop of the actual dark basemap, centred on a real cluster
  centroid, set inline at type height between words. These are genuine tiles
  from the same basemap the explorer uses, not stock imagery.

  The crop is assembled from a 3x3 mosaic of tiles positioned so the target
  coordinate lands at the centre of the fragment. A single tile would fail
  whenever the coordinate sits near a tile edge.
*/

const TILE = 256;

function worldPixel(lat, lng, zoom) {
  const n = 2 ** zoom;
  const latRad = (lat * Math.PI) / 180;
  const x = ((lng + 180) / 360) * n * TILE;
  const y =
    ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n * TILE;
  return { x, y };
}

/*
  Zoom 14 rather than 15: at a fragment only ~90px wide, zoom 15 shows so few
  roads that the crop reads as a black rectangle. One level out puts a
  recognisable junction inside the slot.
*/
export default function MapFragment({ lat, lng, zoom = 14, label }) {
  const { x, y } = worldPixel(lat, lng, zoom);
  const tileX = Math.floor(x / TILE);
  const tileY = Math.floor(y / TILE);

  const tiles = [];
  for (let dx = -1; dx <= 1; dx += 1) {
    for (let dy = -1; dy <= 1; dy += 1) {
      const tx = tileX + dx;
      const ty = tileY + dy;
      tiles.push({
        key: `${tx}-${ty}`,
        // Offset of this tile's top-left corner from the fragment centre.
        left: tx * TILE - x,
        top: ty * TILE - y,
        src: `https://a.basemaps.cartocdn.com/dark_all/${zoom}/${tx}/${ty}.png`,
      });
    }
  }

  return (
    <span
      className="map-fragment"
      role="img"
      aria-label={label ? `Map detail at ${label}` : 'Map detail'}
    >
      <span className="map-fragment__inner" aria-hidden="true">
        {tiles.map((t) => (
          <img
            key={t.key}
            className="map-fragment__tile"
            src={t.src}
            alt=""
            /*
              Not lazy: these sit inside the hero headline, above the fold, and
              are part of the largest contentful paint. Deferring them leaves
              empty slots in the first line of type.
            */
            decoding="async"
            // Lowercase: React 18 does not recognise the camelCase form and
            // passes it through as an unknown DOM attribute with a warning.
            fetchpriority="high"
            width={TILE}
            height={TILE}
            style={{
              left: `calc(50% + ${t.left}px)`,
              top: `calc(50% + ${t.top}px)`,
            }}
          />
        ))}
        <span className="map-fragment__pin" />
      </span>
    </span>
  );
}
