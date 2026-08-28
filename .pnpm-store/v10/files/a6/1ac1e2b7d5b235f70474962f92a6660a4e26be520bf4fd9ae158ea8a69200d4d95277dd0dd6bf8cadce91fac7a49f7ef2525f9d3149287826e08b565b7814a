//#region src/stream/buffer.ts
/**
* Accumulates input and calls stream.parse at safe block boundaries.
*
* @experimental This helper is intended for append-heavy editing flows and is
* not part of the markdown-it compatibility surface.
*/
var StreamBuffer = class {
	md;
	text = "";
	lastFlushedLength = 0;
	constructor(md) {
		this.md = md;
		if (!this.md.stream) throw new Error("StreamBuffer requires a MarkdownIt instance");
	}
	feed(chunk) {
		if (!chunk) return;
		this.text += chunk;
	}
	flushIfBoundary() {
		if (!this.md.stream.enabled) {
			const tokens$1 = this.md.parse(this.text);
			this.lastFlushedLength = this.text.length;
			return tokens$1;
		}
		const prevLen = this.lastFlushedLength;
		if (this.text.length <= prevLen) return null;
		const prev = this.text.slice(0, prevLen);
		const segment = this.text.slice(prevLen);
		if (prevLen === 0) {
			if (segment.charCodeAt(segment.length - 1) !== 10) return null;
			const tokens$1 = this.md.stream.parse(this.text);
			this.lastFlushedLength = this.text.length;
			return tokens$1;
		}
		if (!prev || prev.charCodeAt(prev.length - 1) !== 10) return null;
		if (segment.charCodeAt(segment.length - 1) !== 10) return null;
		let newlineCount = 0;
		for (let i = 0; i < segment.length && newlineCount < 2; i++) if (segment.charCodeAt(i) === 10) newlineCount++;
		if (newlineCount < 2) return null;
		const tokens = this.md.stream.parse(this.text);
		this.lastFlushedLength = this.text.length;
		return tokens;
	}
	flushForce() {
		const tokens = this.md.stream.parse(this.text);
		this.lastFlushedLength = this.text.length;
		return tokens;
	}
	getText() {
		return this.text;
	}
	getTokens() {
		return this.md.stream.peek();
	}
	stats() {
		return this.md.stream.stats();
	}
};

//#endregion
export { StreamBuffer };