// One-off: run the retired Node normaliser over tests/fixtures/titles.json and
// write tests/fixtures/golden_normalize.json. Usage:
//   node tools/make_golden.js /path/to/old/lib/normalize.js
const fs = require('fs'), path = require('path'), Module = require('module');
const srcPath = path.resolve(process.argv[2]);
const m = new Module(srcPath, null); m.filename = srcPath; m.paths = Module._nodeModulePaths(path.dirname(srcPath));
m._compile(fs.readFileSync(srcPath, 'utf8') + '\nmodule.exports.__i={modelKey,groupId,typeOf,brandOf,parsePrice,normalize,specsOf};', srcPath);
const I = m.exports.__i;
const fx = path.join(__dirname, '..', 'tests', 'fixtures');
const rows = JSON.parse(fs.readFileSync(path.join(fx, 'titles.json'), 'utf8'));
const out = rows.map((r) => {
  const n = I.normalize({ title: r.title, price: r.price, mrp: r.mrp, url: 'https://x.test/p' }, r.store);
  if (!n) return { rejected: true };
  const mk = I.modelKey(n.title);
  return { rejected: false, title: n.title, price: n.price, mrp: n.actual_price, brand: n.brand, category: n.product_type,
           model_key: mk, group_id: I.groupId(n.brand, mk, n.title, n.product_type), specs: n.specs };
});
fs.writeFileSync(path.join(fx, 'golden_normalize.json'), JSON.stringify(out));
console.log(out.length, 'rows,', out.filter((o) => o.rejected).length, 'rejected');
