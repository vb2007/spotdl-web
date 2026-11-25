import { createHmac } from 'node:crypto';

// v71: RFC 6238 TOTP (HMAC-SHA1, 30 s, 6 digits) with node's own crypto, as vb2007.hu-api checks
// it. Upstream takes each 30 s step once, and only one newer than the last it took, so a
// code is never reused: `freshTotp` waits for a step this run hasn't used.

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const PERIOD_MS = 30_000;

function base32(secret: string): Buffer {
	let bits = '';
	for (const char of secret.replace(/=+$/, '').toUpperCase()) {
		const value = ALPHABET.indexOf(char);
		if (value < 0) throw new Error('TOTP secret is not base32');
		bits += value.toString(2).padStart(5, '0');
	}
	return Buffer.from((bits.match(/.{8}/g) ?? []).map((byte) => parseInt(byte, 2)));
}

export function totp(secret: string, step: number): string {
	const counter = Buffer.alloc(8);
	counter.writeBigUInt64BE(BigInt(step));
	const digest = createHmac('sha1', base32(secret)).update(counter).digest();
	const offset = digest[digest.length - 1] & 15;
	return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

let lastStep = -1;

/** A code for a 30 s step this run hasn't used, at least 5 s from the step's end (the submit
 * has to reach upstream inside it), waiting for the next step when needed. */
export async function freshTotp(secret: string): Promise<string> {
	for (;;) {
		const now = Date.now();
		const step = Math.floor(now / PERIOD_MS);
		const left = (step + 1) * PERIOD_MS - now;
		if (step > lastStep && left > 5_000) {
			lastStep = step;
			return totp(secret, step);
		}
		await new Promise((resolve) => setTimeout(resolve, left + 250));
	}
}
