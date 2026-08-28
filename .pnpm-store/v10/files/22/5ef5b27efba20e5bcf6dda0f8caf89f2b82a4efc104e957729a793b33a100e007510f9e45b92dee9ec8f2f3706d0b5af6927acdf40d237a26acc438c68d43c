/**
 * Link utilities for normalizing and validating URLs
 */
/**
 * Validate URL to prevent XSS attacks.
 * This validator can prohibit more than really needed to prevent XSS.
 * It's a tradeoff to keep code simple and to be secure by default.
 */
export declare function validateLink(url: string): boolean;
/**
 * Normalize link URL by encoding hostname to ASCII (punycode)
 */
export declare function normalizeLink(url: string): string;
/**
 * Normalize link text by decoding hostname from punycode to Unicode
 */
export declare function normalizeLinkText(url: string): string;
