//#region src/stream/debounced.ts
/**
* Debounced stream parser wrapper for real-time editing scenarios.
*
* When user types character-by-character, it's inefficient to parse on every keystroke.
* This wrapper debounces parse calls to balance responsiveness and performance.
*
* @example
* ```typescript
* const md = MarkdownIt({ stream: true })
* const debouncedParser = new DebouncedStreamParser(md, 100) // 100ms debounce
*
* editor.on('change', (text) => {
*   debouncedParser.parse(text, (tokens) => {
*     // Render tokens
*     renderMarkdown(tokens)
*   })
* })
* ```
*/
var DebouncedStreamParser = class {
	md;
	debounceMs;
	timeoutId = null;
	pendingCallback = null;
	lastText = "";
	lastTokens = [];
	/**
	* @param md - MarkdownIt instance with stream enabled
	* @param debounceMs - Milliseconds to wait before parsing (default: 150ms)
	*/
	constructor(md, debounceMs = 150) {
		this.md = md;
		this.debounceMs = debounceMs;
	}
	/**
	* Parse text with debouncing. Callback is called with the parsed tokens.
	*
	* @param text - Markdown text to parse
	* @param callback - Called with tokens when parsing completes
	* @param immediate - If true, parse immediately without debouncing
	*/
	parse(text, callback, immediate = false) {
		if (text === this.lastText) {
			callback(this.lastTokens);
			return;
		}
		this.pendingCallback = callback;
		if (immediate) {
			this.executeParse(text);
			return;
		}
		if (this.timeoutId) clearTimeout(this.timeoutId);
		this.timeoutId = setTimeout(() => {
			this.executeParse(text);
		}, this.debounceMs);
	}
	/**
	* Cancel any pending parse operation
	*/
	cancel() {
		if (this.timeoutId) {
			clearTimeout(this.timeoutId);
			this.timeoutId = null;
		}
		this.pendingCallback = null;
	}
	/**
	* Force immediate parse, bypassing debounce
	*/
	flush(text) {
		this.cancel();
		this.executeParse(text);
		return this.lastTokens;
	}
	/**
	* Reset the parser state
	*/
	reset() {
		this.cancel();
		this.md.stream.reset();
		this.lastText = "";
		this.lastTokens = [];
	}
	executeParse(text) {
		this.lastText = text;
		this.lastTokens = this.md.stream.parse(text);
		if (this.pendingCallback) {
			this.pendingCallback(this.lastTokens);
			this.pendingCallback = null;
		}
		this.timeoutId = null;
	}
	/**
	* Get parser statistics
	*/
	getStats() {
		return this.md.stream.stats();
	}
};
/**
* Throttled stream parser wrapper - limits parse frequency.
* Unlike debouncing, throttling ensures parsing happens at regular intervals
* even during continuous typing.
*
* @example
* ```typescript
* const md = MarkdownIt({ stream: true })
* const throttledParser = new ThrottledStreamParser(md, 200) // Parse at most every 200ms
*
* editor.on('change', (text) => {
*   throttledParser.parse(text, (tokens) => {
*     renderMarkdown(tokens)
*   })
* })
* ```
*/
var ThrottledStreamParser = class {
	md;
	throttleMs;
	lastParseTime = 0;
	timeoutId = null;
	pendingText = null;
	pendingCallback = null;
	lastTokens = [];
	constructor(md, throttleMs = 200) {
		this.md = md;
		this.throttleMs = throttleMs;
	}
	parse(text, callback) {
		const timeSinceLastParse = Date.now() - this.lastParseTime;
		if (timeSinceLastParse >= this.throttleMs) {
			this.executeParse(text, callback);
			return;
		}
		this.pendingText = text;
		this.pendingCallback = callback;
		if (!this.timeoutId) {
			const remainingTime = this.throttleMs - timeSinceLastParse;
			this.timeoutId = setTimeout(() => {
				if (this.pendingText && this.pendingCallback) this.executeParse(this.pendingText, this.pendingCallback);
				this.timeoutId = null;
				this.pendingText = null;
				this.pendingCallback = null;
			}, remainingTime);
		}
	}
	cancel() {
		if (this.timeoutId) {
			clearTimeout(this.timeoutId);
			this.timeoutId = null;
		}
		this.pendingText = null;
		this.pendingCallback = null;
	}
	reset() {
		this.cancel();
		this.md.stream.reset();
		this.lastParseTime = 0;
		this.lastTokens = [];
	}
	executeParse(text, callback) {
		this.lastParseTime = Date.now();
		this.lastTokens = this.md.stream.parse(text);
		callback(this.lastTokens);
	}
	getStats() {
		return this.md.stream.stats();
	}
};

//#endregion
export { DebouncedStreamParser, ThrottledStreamParser };