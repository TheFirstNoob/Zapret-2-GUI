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

const img = decodePNG(process.argv[2]);
// region: x 205..300, y 30..150, cell=2
const x0 = 205, y0 = 30, x1 = 300, y1 = 150;
for (let y = y0; y < y1; y += 2) {
  let line = '';
  for (let x = x0; x < x1; x += 2) {
    const i = (y * img.width + x) * 3;
    const r = img.rgba[i], g = img.rgba[i + 1], b = img.rgba[i + 2];
    if (r === 45 && g === 50 && b === 55) line += '|';
    else if (r === 18 && g === 20 && b === 22) line += '#';
    else if (r === 29 && g === 32 && b === 35) line += '=';
    else if (r === 22 && g === 24 && b === 27) line += '.';
    else if ((r + g + b) / 3 > 120) line += '@';
    else line += '?';
  }
  console.log(String(y).padStart(4) + ' ' + line);
}