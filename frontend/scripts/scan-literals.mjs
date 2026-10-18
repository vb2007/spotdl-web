// v46: the "no hard-coded user-visible string" scan, run by `lint`.
//
// Flags, in frontend/src:
// - template text containing a letter (Svelte's own parser, so markup and {expressions} are
//   told apart exactly);
// - a static `aria-label`, `title`, `placeholder`, `alt` or `aria-description` value with a
//   letter;
// - a string or template literal in a <script> or a .ts module that reads like prose: two or
//   more words of letters (the TypeScript parser, so comments never count).
//
// A deliberate exception carries an `i18n-ignore` comment on its line or the line above, with
// the reason; the PR lists each one. Generated code (src/lib/paraglide) and tests are skipped.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { parse } from 'svelte/compiler';
import ts from 'typescript';

const root = path.resolve(import.meta.dirname, '..');
const src = path.join(root, 'src');
const SKIP_DIRS = new Set([path.join(src, 'lib/paraglide')]);
const ATTRIBUTES = new Set(['aria-label', 'title', 'placeholder', 'alt', 'aria-description']);
const LETTER = /\p{L}/u;
// Two words of two or more letters, separated by a space: "Could not", "show shortcuts".
const PROSE = /\p{L}{2,}[,.:;!?']*\s+[\p{L}(“"']/u;

function files(dir) {
	const out = [];
	for (const name of readdirSync(dir)) {
		const full = path.join(dir, name);
		if (SKIP_DIRS.has(full)) continue;
		if (statSync(full).isDirectory()) out.push(...files(full));
		else if (/\.(svelte|ts)$/.test(name) && !/\.test\.ts$|\.d\.ts$/.test(name)) out.push(full);
	}
	return out;
}

function lineOf(source, offset) {
	return source.slice(0, offset).split('\n').length;
}

function ignored(lines, line) {
	return [lines[line - 1], lines[line - 2]].some((text) => text?.includes('i18n-ignore'));
}

const findings = [];

function report(file, source, lines, offset, kind, text) {
	const line = lineOf(source, offset);
	if (ignored(lines, line)) return;
	findings.push(`${path.relative(root, file)}:${line}  ${kind}: ${JSON.stringify(text.trim())}`);
}

function scanScript(file, source, lines, code, base) {
	const sf = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
	const visit = (node) => {
		if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
		// A type's string literals ('settled:partial' | ...) are never shown.
		if (ts.isLiteralTypeNode(node)) return;
		let pieces = [];
		if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) pieces = [node.text];
		else if (ts.isTemplateExpression(node))
			pieces = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)];
		const prose = pieces.find((piece) => PROSE.test(piece));
		if (prose !== undefined) {
			report(file, source, lines, base + node.getStart(sf), 'script string', prose);
			return;
		}
		ts.forEachChild(node, visit);
	};
	visit(sf);
}

// The parts of an expression that end up as text: `{a ? 'x' : 'y'}` shows 'x' or 'y', but
// `{a === 'x' ? …}` compares 'x' and `{m.key()}` calls a message. Only string literals in an
// output position count.
function outputLiterals(expr, out = []) {
	if (!expr) return out;
	switch (expr.type) {
		case 'Literal':
			if (typeof expr.value === 'string') out.push({ text: expr.value, start: expr.start });
			break;
		case 'ConditionalExpression':
			outputLiterals(expr.consequent, out);
			outputLiterals(expr.alternate, out);
			break;
		case 'LogicalExpression':
			outputLiterals(expr.left, out);
			outputLiterals(expr.right, out);
			break;
		case 'TemplateLiteral':
			for (const quasi of expr.quasis)
				out.push({ text: quasi.value.cooked ?? '', start: quasi.start });
			for (const inner of expr.expressions) outputLiterals(inner, out);
			break;
	}
	return out;
}

function walkTemplate(file, source, lines, node, inComponent = false) {
	if (!node || typeof node !== 'object') return;
	if (Array.isArray(node))
		return node.forEach((child) => walkTemplate(file, source, lines, child, inComponent));
	switch (node.type) {
		case 'Text':
			if (LETTER.test(node.data))
				report(file, source, lines, node.start, 'template text', node.data);
			return;
		case 'ExpressionTag':
			for (const literal of outputLiterals(node.expression))
				if (LETTER.test(literal.text))
					report(file, source, lines, literal.start, 'template expression', literal.text);
			return;
		case 'Attribute': {
			// A text attribute shows any letter; a component prop is often a key ("account"),
			// so there only prose counts. Every other element attribute (class, id, type…) is
			// markup.
			const test = ATTRIBUTES.has(node.name) ? LETTER : inComponent ? PROSE : null;
			if (!test || (!Array.isArray(node.value) && node.value === true)) return;
			for (const part of [node.value].flat()) {
				if (part.type === 'Text' && test.test(part.data))
					report(file, source, lines, part.start, `${node.name}=`, part.data);
				if (part.type === 'ExpressionTag')
					for (const literal of outputLiterals(part.expression))
						if (test.test(literal.text))
							report(file, source, lines, literal.start, `${node.name}=`, literal.text);
			}
			return;
		}
		// A `style:`/`class:` directive's value is CSS, never shown.
		case 'StyleSheet':
		case 'StyleDirective':
		case 'ClassDirective':
			return;
	}
	const component = node.type === 'Component' || node.type === 'SvelteComponent';
	for (const [key, value] of Object.entries(node)) {
		if (key === 'parent' || key === 'metadata') continue;
		if (value && typeof value === 'object')
			walkTemplate(file, source, lines, value, key === 'attributes' ? component : false);
	}
}

for (const file of files(src)) {
	const source = readFileSync(file, 'utf8');
	const lines = source.split('\n');
	if (file.endsWith('.ts')) {
		scanScript(file, source, lines, source, 0);
		continue;
	}
	const ast = parse(source, { modern: true });
	for (const script of [ast.instance, ast.module].filter(Boolean)) {
		const start = script.content.start;
		scanScript(file, source, lines, source.slice(start, script.content.end), start);
	}
	walkTemplate(file, source, lines, ast.fragment);
}

if (findings.length) {
	console.error(
		`i18n: ${findings.length} hard-coded string(s) in src/ (mark a deliberate one i18n-ignore):`
	);
	for (const finding of findings) console.error(`  ${finding}`);
	process.exit(1);
}
console.log('i18n: no hard-coded user-visible strings in src/.');
