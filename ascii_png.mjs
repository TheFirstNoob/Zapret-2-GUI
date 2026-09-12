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
const cell = 6, cols = Math.floor(img.width / cell), rows = Math.min(Math.floor(img.height / cell), 16);
// classify each cell by average color: dark strip (#121416), panel (#1d2023), bg (#16181b), border (#2d3237), accent, text (light)
const ramp = ' .:-=+*#%@';
let art = '';
for (let cy = 0; cy < rows; cy++) {
  let line = '';
  for (let cx = 0; cx < cols; cx++) {
    let r = 0, g = 0, b = 0, n = 0;
    for (let y = cy * cell; y < (cy + 1) * cell && y < img.height; y += 2)
      for (let x = cx * cell; x < (cx + 1) * cell && x < img.width; x += 2) {
        const i = (y * img.width + x) * 3;
        r += img.rgba[i]; g += img.rgba[i + 1]; b += img.rgba[i + 2]; n++;
      }
    r /= n; g /= n; b /= n;
    const lum = (r * 0.3 + g * 0.59 + b * 0.11);
    // classify
    if (Math.abs(r - 18) < 4 && Math.abs(g - 20) < 4 && Math.abs(b - 22) < 4) line += '#'; // strip #121416
    else if (Math.abs(r - 29) < 4 && Math.abs(g - 32) < 4 && Math.abs(b - 35) < 4) line += '='; // panel #1d2023
    else if (Math.abs(r - 22) < 4 && Math.abs(g - 24) < 4 && Math.abs(b - 27) < 4) line += '.'; // bg #16181b
    else if (Math.abs(r - 45) < 6 && Math.abs(g - 50) < 6 && Math.abs(b - 55) < 6) line += '|'; // border #2d3237
    else if (lum > 110) line += '@'; // text/light
    else line += ' ';
  }
  art += line + '\n';
}
console.log(art);
