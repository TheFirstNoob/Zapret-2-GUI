import fs from 'node:fs';
import zlib from 'node:zlib';

function decodePNG(file) {
  const buf = fs.readFileSync(file);
  let pos = 8, width = 0, height = 0, bitDepth = 0, colorType = 0, idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString('ascii', pos + 4, pos + 8);
    const data = buf.subarray(pos + 8, pos + 8 + len);
    if (type === 'IHDR') { width = data.readUInt32BE(0); height = data.readUInt32BE(4); bitDepth = data[8]; colorType = data[9]; }
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    pos += 12 + len;
  }
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const bpp = colorType === 6 ? 4 : 3, stride = width * bpp;
  const out = new Uint8Array(width * height * bpp);
  let prev = new Uint8Array(stride), cur = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const row = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    cur.fill(0);
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? cur[x - bpp] : 0;
      const b = prev[x];
      const c = x >= bpp ? prev[x - bpp] : 0;
      let v = row[x];
      switch (filter) {
        case 1: v = (v + a) & 255; break;
        case 2: v = (v + b) & 255; break;
        case 3: v = (v + ((a + b) >> 1)) & 255; break;
        case 4: { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
          v = (v + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255; break; }
      }
      cur[x] = v;
    }
    out.set(cur, y * stride);
    const tmp = prev; prev = cur; cur = tmp;
  }
  return { width, height, rgba: out, bpp };
}

const a = decodePNG('shot_diag.png');
const b = decodePNG('shot_cdn.png');
const SHIFT = 12; // cdn panel is 12px lower
const regions = [];
for (let y = 0; y + SHIFT < a.height; y++) {
  for (let x = 0; x < a.width; x++) {
    const i1 = (y * a.width + x) * 3;
    const i2 = ((y + SHIFT) * b.width + x) * 3;
    if (a.rgba[i1] !== b.rgba[i2] || a.rgba[i1 + 1] !== b.rgba[i2 + 1] || a.rgba[i1 + 2] !== b.rgba[i2 + 2]) {
      const ry = Math.floor(y / 10) * 10, rx = Math.floor(x / 40) * 40;
      const key = ry + ':' + rx;
      if (!regions.length || regions[regions.length - 1].key !== key) regions.push({ key, count: 1 });
      else regions[regions.length - 1].count++;
    }
  }
}
console.log('diff regions (y:x, count):', JSON.stringify(regions.slice(0, 40)));