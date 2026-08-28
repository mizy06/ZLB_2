/**
 * class Token
 *
 * Create new token and fill passed properties.
 */
export declare class Token<Meta = any> {
    /**
     * Token#type -> String
     *
     * Type of the token (string, e.g. "paragraph_open")
     */
    type: string;
    /**
     * Token#tag -> String
     *
     * html tag name, e.g. "p"
     */
    tag: string;
    /**
     * Token#attrs -> Array
     *
     * Html attributes. Format: `[ [ name1, value1 ], [ name2, value2 ] ]`
     */
    attrs: [string, string][] | null;
    /**
     * Token#map -> Array
     *
     * Source map info. Format: `[ line_begin, line_end ]`
     */
    map: number[] | null;
    /**
     * Token#nesting -> Number
     *
     * Level change (number in {-1, 0, 1} set), where:
     *
     * -  `1` means the tag is opening
     * -  `0` means the tag is self-closing
     * - `-1` means the tag is closing
     */
    nesting: number;
    /**
     * Token#level -> Number
     *
     * nesting level, the same as `state.level`
     */
    level: number;
    /**
     * Token#children -> Array
     *
     * An array of child nodes (inline and img tokens)
     */
    children: Token[] | null;
    /**
     * Token#content -> String
     *
     * In a case of self-closing tag (code, html, fence, etc.),
     * it has contents of this tag.
     */
    content: string;
    /**
     * Token#markup -> String
     *
     * '*' or '_' for emphasis, fence string for fence, etc.
     */
    markup: string;
    /**
     * Token#info -> String
     *
     * Additional information:
     *
     * - Info string for "fence" tokens
     * - The value "auto" for autolink "link_open" and "link_close" tokens
     * - The string value of the item marker for ordered-list "list_item_open" tokens
     */
    info: string;
    /**
     * Token#meta -> Object
     *
     * A place for plugins to store an arbitrary data
     */
    meta: Meta | null;
    /**
     * Token#block -> Boolean
     *
     * True for block-level tokens, false for inline tokens.
     * Used in renderer to calculate line breaks
     */
    block: boolean;
    /**
     * Token#hidden -> Boolean
     *
     * If it's true, ignore this element when rendering. Used for tight lists
     * to hide paragraphs.
     */
    hidden: boolean;
    constructor(type: string, tag: string, nesting: number);
    /**
     * Token.attrIndex(name) -> Number
     *
     * Search attribute index by name.
     */
    attrIndex(name: string): number;
    /**
     * Token.attrPush(attrData)
     *
     * Add `[ name, value ]` attribute to list. Init attrs if necessary
     */
    attrPush(attrData: [string, string]): void;
    /**
     * Token.attrSet(name, value)
     *
     * Set `name` attribute to `value`. Override old value if exists.
     */
    attrSet(name: string, value: string): void;
    /**
     * Token.attrGet(name)
     *
     * Get the value of attribute `name`, or null if it does not exist.
     */
    attrGet(name: string): string | null;
    /**
     * Token.attrJoin(name, value)
     *
     * Join value to existing attribute via space. Or create new attribute if not
     * exists. Useful to operate with token classes.
     */
    attrJoin(name: string, value: string): void;
}
export default Token;
