import * as y from './y0lib.mjs';
const { page } = await y.attach();
console.log(page.url());
const t = await y.snap(page, process.argv[2] || 'peek');
console.log(t.split('\n').filter(l=>/menuitem|radio|Settings trigger|credits|Agent|prompt|textbox/.test(l)).slice(0,50).join('\n'));
process.exit(0);
