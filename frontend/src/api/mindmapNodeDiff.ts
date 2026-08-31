export interface MindmapNodeDescriptor {
  id: string;
  name: string;
}

type ParsedEvent = MindmapNodeDescriptor[];

function nodeDescriptor(value: unknown): MindmapNodeDescriptor | null {
  if (!value || typeof value !== 'object') return null;
  const node = value as Record<string, unknown>;
  const id = typeof node.id === 'string' ? node.id.trim() : '';
  const name = typeof node.name === 'string' ? node.name.trim() : '';
  if (!id && !name) return null;
  return {
    id: id || name,
    name: name || id,
  };
}

export function mindmapNodeMap(nodes: unknown): Map<string, string> {
  const result = new Map<string, string>();
  if (!Array.isArray(nodes)) return result;
  for (const value of nodes) {
    const node = nodeDescriptor(value);
    if (node) result.set(node.id, node.name);
  }
  return result;
}

/**
 * Incrementally extracts complete objects from the top-level `nodes` array of
 * a streamed mind-map JSON object. It keeps tokenizer state across chunks, so
 * split strings, escaped quotes, and nested objects do not produce false nodes.
 */
export class MindmapNodeStreamTracker {
  private seekState: 'scan' | 'colon' | 'array' = 'scan';
  private seekInString = false;
  private seekEscape = false;
  private seekString = '';
  private inNodes = false;
  private nodesClosed = false;
  private objectDepth = 0;
  private objectBuffer = '';
  private objectInString = false;
  private objectEscape = false;

  get complete(): boolean {
    return this.nodesClosed;
  }

  push(chunk: string): ParsedEvent {
    const nodes: MindmapNodeDescriptor[] = [];
    if (!chunk || this.nodesClosed) return nodes;

    for (const char of chunk) {
      if (!this.inNodes) {
        this.scanForNodesArray(char);
        continue;
      }
      const node = this.scanNodeArray(char);
      if (node) nodes.push(node);
      if (this.nodesClosed) break;
    }
    return nodes;
  }

  private scanForNodesArray(char: string): void {
    if (this.seekInString) {
      if (this.seekEscape) {
        this.seekEscape = false;
        this.seekString += char;
        return;
      }
      if (char === '\\') {
        this.seekEscape = true;
        return;
      }
      if (char === '"') {
        this.seekInString = false;
        this.seekState = this.seekString === 'nodes' ? 'colon' : 'scan';
        this.seekString = '';
        return;
      }
      this.seekString += char;
      return;
    }

    if (this.seekState === 'colon') {
      if (/\s/.test(char)) return;
      this.seekState = char === ':' ? 'array' : 'scan';
      return;
    }
    if (this.seekState === 'array') {
      if (/\s/.test(char)) return;
      if (char === '[') {
        this.inNodes = true;
      } else {
        this.seekState = 'scan';
      }
      return;
    }
    if (char === '"') {
      this.seekInString = true;
      this.seekEscape = false;
      this.seekString = '';
    }
  }

  private scanNodeArray(char: string): MindmapNodeDescriptor | null {
    if (this.objectDepth === 0) {
      if (char === ']') {
        this.nodesClosed = true;
        return null;
      }
      if (char !== '{') return null;
      this.objectDepth = 1;
      this.objectBuffer = '{';
      this.objectInString = false;
      this.objectEscape = false;
      return null;
    }

    this.objectBuffer += char;
    if (this.objectInString) {
      if (this.objectEscape) {
        this.objectEscape = false;
      } else if (char === '\\') {
        this.objectEscape = true;
      } else if (char === '"') {
        this.objectInString = false;
      }
      return null;
    }

    if (char === '"') {
      this.objectInString = true;
      return null;
    }
    if (char === '{') {
      this.objectDepth += 1;
      return null;
    }
    if (char !== '}') return null;

    this.objectDepth -= 1;
    if (this.objectDepth !== 0) return null;
    const raw = this.objectBuffer;
    this.objectBuffer = '';
    try {
      return nodeDescriptor(JSON.parse(raw));
    } catch {
      return null;
    }
  }
}
