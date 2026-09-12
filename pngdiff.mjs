import fs from 'node:fs';
import zlib from 'node:zlib';

function decodePNG(file) {
  const buf = fs.readFileSync(file);
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('not png');
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
  if (bitDepth !== 8 || (colorType !== 6 && colorType !== 2)) throw new Error('unsupported ' + bitDepth + '/' + colorType);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const bpp = colorType === 6 ? 4 : 3, stride = width * bpp;
  const out = new Uint8Array(width * height * (bpp === 4 ? 4 : 3));
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

const px = (img, x, y) => {
  const i = (y * img.width + x) * img.bpp;
  return [img.rgba[i], img.rgba[i + 1], img.rgba[i + 2]];
};

const diag = decodePNG('shot_diag.png');
const cdn = decodePNG('shot_cdn.png');

function scan(img, yTop) {
  return {
    topBorder: [px(img, 216, yTop), px(img, 730, yTop), px(img, 1264, yTop)],
    stripBg: [px(img, 300, yTop + 10), px(img, 730, yTop + 10)],
    sideBorderAtStrip: [px(img, 216, yTop + 25), px(img, 1264, yTop + 25)],
    contentBg: px(img, 730, yTop + 60),
  };
}
console.log('DIAG:', JSON.stringify(scan(diag, 42)));
console.log('CDN :', JSON.stringify(scan(cdn, 54)));