//#region src/support/chunk_recommend.ts
const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;
function normalizeOptions(opts) {
	return opts.experimental ? {
		...opts,
		...opts.experimental
	} : opts;
}
const FULL_DISCRETE_RECOMMENDATIONS = [
	{
		max: 5e3,
		strategy: "discrete",
		maxChunkChars: 32e3,
		maxChunkLines: 150,
		maxChunks: 8,
		notes: "<=5k"
	},
	{
		max: 2e4,
		strategy: "discrete",
		maxChunkChars: 24e3,
		maxChunkLines: 200,
		maxChunks: 12,
		notes: "<=20k"
	},
	{
		max: 1e5,
		strategy: "plain",
		notes: "<=100k plain"
	},
	{
		max: 2e5,
		strategy: "discrete",
		maxChunkChars: 2e4,
		maxChunkLines: 150,
		maxChunks: 12,
		notes: "<=200k"
	},
	{
		max: 5e5,
		strategy: "discrete",
		maxChunkChars: 64e3,
		maxChunkLines: 700,
		maxChunks: 16,
		notes: "<=500k"
	},
	{
		max: 5e6,
		strategy: "discrete",
		maxChunkChars: 64e3,
		maxChunkLines: 700,
		maxChunks: 16,
		notes: "<=5M"
	}
];
const STREAM_DISCRETE_RECOMMENDATIONS = [
	{
		max: 5e3,
		strategy: "discrete",
		maxChunkChars: 16e3,
		maxChunkLines: 250,
		maxChunks: 8,
		notes: "<=5k"
	},
	{
		max: 2e4,
		strategy: "discrete",
		maxChunkChars: 2e4,
		maxChunkLines: 200,
		maxChunks: 24,
		notes: "<=20k"
	},
	{
		max: 1e5,
		strategy: "discrete",
		maxChunkChars: 2e4,
		maxChunkLines: 200,
		maxChunks: 24,
		notes: "<=100k"
	},
	{
		max: 5e5,
		strategy: "discrete",
		maxChunkChars: 64e3,
		maxChunkLines: 700,
		maxChunks: 32,
		notes: "<=500k"
	},
	{
		max: 5e6,
		strategy: "discrete",
		maxChunkChars: 64e3,
		maxChunkLines: 700,
		maxChunks: 32,
		notes: "<=5M"
	}
];
function toRecommendation(fenceAware, discrete) {
	return {
		strategy: discrete.strategy,
		maxChunkChars: discrete.maxChunkChars,
		maxChunkLines: discrete.maxChunkLines,
		maxChunks: discrete.maxChunks,
		fenceAware,
		notes: discrete.notes
	};
}
/**
* Suggest full-parse chunk settings for the current synthetic harness defaults.
*
* @experimental Recommendations are workload-dependent; validate on the corpus
* you plan to parse.
*/
function recommendFullChunkStrategy(sizeChars, sizeLines = Math.max(0, sizeChars / 40 | 0), opts = {}) {
	const options = normalizeOptions(opts);
	const fenceAware = options.fullChunkFenceAware ?? true;
	const target = options.fullChunkTargetChunks ?? 8;
	const adaptive = options.fullChunkAdaptive !== false;
	for (let i = 0; i < FULL_DISCRETE_RECOMMENDATIONS.length; i++) {
		const rec = FULL_DISCRETE_RECOMMENDATIONS[i];
		if (sizeChars <= rec.max) {
			if (rec.strategy !== "adaptive") return toRecommendation(fenceAware, rec);
			break;
		}
	}
	if (sizeChars > 5e6) return {
		strategy: "plain",
		fenceAware,
		notes: ">5M plain"
	};
	if (adaptive) return {
		strategy: "adaptive",
		maxChunkChars: clamp(Math.ceil(sizeChars / target), 8e3, 64e3),
		maxChunkLines: clamp(Math.ceil(sizeLines / target), 150, 700),
		maxChunks: clamp(Math.ceil(sizeChars / 64e3), target, 16),
		fenceAware,
		notes: "adaptive fallback"
	};
	return {
		strategy: "discrete",
		maxChunkChars: options.fullChunkSizeChars ?? 1e4,
		maxChunkLines: options.fullChunkSizeLines ?? 200,
		fenceAware,
		maxChunks: options.fullChunkMaxChunks
	};
}
/**
* Suggest stream chunk settings for the current synthetic harness defaults.
*
* @experimental Recommendations are workload-dependent; validate on the corpus
* you plan to parse.
*/
function recommendStreamChunkStrategy(sizeChars, sizeLines = Math.max(0, sizeChars / 40 | 0), opts = {}) {
	const options = normalizeOptions(opts);
	const fenceAware = options.streamChunkFenceAware ?? true;
	const target = options.streamChunkTargetChunks ?? 8;
	const adaptive = options.streamChunkAdaptive !== false;
	for (let i = 0; i < STREAM_DISCRETE_RECOMMENDATIONS.length; i++) {
		const rec = STREAM_DISCRETE_RECOMMENDATIONS[i];
		if (sizeChars <= rec.max) {
			if (rec.strategy !== "adaptive") return toRecommendation(fenceAware, rec);
			break;
		}
	}
	if (sizeChars > 5e6) return {
		strategy: "plain",
		fenceAware,
		notes: ">5M plain"
	};
	if (adaptive) return {
		strategy: "adaptive",
		maxChunkChars: clamp(Math.ceil(sizeChars / target), 8e3, 64e3),
		maxChunkLines: clamp(Math.ceil(sizeLines / target), 150, 700),
		maxChunks: clamp(Math.ceil(sizeChars / 64e3), target, 32),
		fenceAware,
		notes: "adaptive fallback"
	};
	return {
		strategy: "discrete",
		maxChunkChars: options.streamChunkSizeChars ?? 1e4,
		maxChunkLines: options.streamChunkSizeLines ?? 200,
		maxChunks: options.streamChunkMaxChunks,
		fenceAware
	};
}

//#endregion
export { recommendFullChunkStrategy, recommendStreamChunkStrategy };